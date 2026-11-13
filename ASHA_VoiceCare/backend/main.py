from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional
from pathlib import Path
import sqlite3, json, re, uuid, os, tempfile
from datetime import date
import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE = Path(__file__).resolve().parent.parent
DB_PATH = BASE / "asha_voicecare.db"
RULES_PATH = BASE / "data" / "danger_signs.json"

app = FastAPI(title="ASHA VoiceCare API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS visits (
            visit_id TEXT PRIMARY KEY,
            beneficiary_id TEXT NOT NULL,
            visit_type TEXT,
            weight_kg REAL,
            vaccination_status TEXT,
            vaccinations_due TEXT,
            next_visit_date TEXT,
            original_note TEXT,
            confirmed INTEGER NOT NULL DEFAULT 0,
            danger_flag INTEGER NOT NULL DEFAULT 0,
            danger_matches TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS followups (
            task_id TEXT PRIMARY KEY,
            visit_id TEXT NOT NULL,
            beneficiary_id TEXT NOT NULL,
            task_description TEXT NOT NULL,
            due_date TEXT,
            priority TEXT DEFAULT 'normal',
            status TEXT DEFAULT 'pending'
        )""")

init_db()

class ExtractRequest(BaseModel):
    note: str = Field(min_length=2, max_length=5000)
    beneficiary_id: Optional[str] = None

class VisitRecord(BaseModel):
    beneficiary_id: str
    visit_type: Optional[str] = None
    weight_kg: Optional[float] = None
    vaccination_status: Optional[str] = None
    vaccinations_due: Optional[str] = None
    next_visit_date: Optional[str] = None
    original_note: str
    confirmed: bool = False

class ConfirmRequest(BaseModel):
    record: VisitRecord

def load_rules():
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))

def danger_check(note: str):
    low = note.lower()
    matches = []
    for rule in load_rules():
        if any(term.lower() in low for term in rule["phrases"]):
            matches.append({
                "rule_id": rule["id"],
                "label": rule["label"],
                "referral_message": rule["referral_message"]
            })
    return matches


def extract_weight(note: str):
    patterns = [
        r"(?:weight|weighs?|wazan|ತೂಕ)\s*(?:is|of|=)?\s*(\d+(?:\.\d+)?)\s*(?:kg|kilo(?:gram)?s?)",
        r"(\d+(?:\.\d+)?)\s*(?:kg|kilo(?:gram)?s?)"
    ]

    for pattern in patterns:
        m = re.search(pattern, note, re.IGNORECASE)
        if m:
            try:
                value = float(m.group(1))
                if 0.2 <= value <= 200:
                    return value
            except ValueError:
                pass

    return None


def extract_date(note: str):
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", note)
    if m:
        d, mo, y = map(int, m.groups())
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None

    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", note)
    return m.group(1) if m else None


def extract_record(note: str, beneficiary_id: Optional[str]):
    low = note.lower()
    bid = beneficiary_id
    if not bid:
        m = re.search(r"(?:beneficiary\\s*id|id)\\s*[:#-]?\\s*([a-z0-9-]+)", note, re.I)
        bid = m.group(1) if m else ""
    visit_type = None
    for key, label in [
        ("anc", "ANC"), ("antenatal", "ANC"), ("pregnancy", "ANC"),
        ("pnc", "PNC"), ("postnatal", "PNC"), ("newborn", "Newborn"),
        ("immunisation", "Immunisation"), ("immunization", "Immunisation"),
        ("vaccination", "Immunisation")
    ]:
        if key in low:
            visit_type = label
            break
    vaccination_status = None
    if any(x in low for x in ["completed", "given", "administered"]):
        vaccination_status = "Completed (confirm vaccine name)"
    elif any(x in low for x in ["due", "pending", "not given"]):
        vaccination_status = "Due / pending (confirm vaccine name)"
    due = "IFA mentioned" if any(x in low for x in ["ifa", "iron folic"]) else None
    if any(x in low for x in ["tt injection", "tetanus"]):
        due = (due + "; " if due else "") + "TT mentioned"
    return {
        "beneficiary_id": bid,
        "visit_type": visit_type,
        "weight_kg": extract_weight(note),
        "vaccination_status": vaccination_status,
        "vaccinations_due": due,
        "next_visit_date": extract_date(note),
        "original_note": note,
        "confirmed": False
    }

@app.get("/api/health")
def health():
    return {"status": "ok", "app": "ASHA VoiceCare"}

# Hybrid speech-to-text: cloud transcription first, local faster-whisper fallback.
# The browser also keeps its native speech recognizer as a last-resort fallback.
_WHISPER_MODEL = None

def _local_transcribe(audio_path: str, language_code: str) -> str:
    global _WHISPER_MODEL
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Local speech model is not installed. Run: pip install -r requirements-voice.txt") from exc
    if _WHISPER_MODEL is None:
        model_name = os.getenv("ASHA_WHISPER_MODEL", "small")
        _WHISPER_MODEL = WhisperModel(model_name, device="cpu", compute_type="int8")
    lang = language_code.split("-")[0].lower()
    segments, _info = _WHISPER_MODEL.transcribe(
        audio_path,
        language=lang,
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
        initial_prompt=("Kannada community health visit. Medical terms: ANC, PNC, ಗರ್ಭಿಣಿ, ತೂಕ, ರಕ್ತದೊತ್ತಡ, ಲಸಿಕೆ, TT, IFA, kilograms.") if lang == "kn" else None,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()

@app.post("/api/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    language: str = Form("kn-IN"),
):
    """Transcribe a browser-recorded audio clip. Never expose API keys to the browser."""
    allowed = {"audio/webm", "audio/ogg", "audio/wav", "audio/mp4", "audio/mpeg", "audio/x-wav"}
    content_type = (audio.content_type or "").split(";")[0].lower()
    if content_type not in allowed:
        raise HTTPException(415, "Unsupported audio format. Please use Chrome or Edge and record again.")
    raw = await audio.read()
    if not raw:
        raise HTTPException(400, "No audio was captured. Check microphone permission and try again.")
    if len(raw) > 24 * 1024 * 1024:
        raise HTTPException(413, "Recording is too large. Please record a shorter note (under 5 minutes).")

    suffix = ".webm" if "webm" in content_type else ".ogg" if "ogg" in content_type else ".wav" if "wav" in content_type else ".mp4" if "mp4" in content_type else ".mp3" if "mpeg" in content_type else ".audio"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            temp_path = tmp.name

        errors = []
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if api_key:
            try:
                data = {"model": os.getenv("ASHA_CLOUD_STT_MODEL", "gpt-transcribe"), "response_format": "json"}
                data["prompt"] = (
                    "ASHA community health home-visit dictation. The speaker may use Kannada "
                    "with English medical abbreviations. Preserve the spoken language and do not "
                    "invent missing words. Common context terms include ANC, PNC, TT, IFA, "
                    "ಗರ್ಭಿಣಿ, ತೂಕ, ರಕ್ತದೊತ್ತಡ and ಲಸಿಕೆ."
                )
                async with httpx.AsyncClient(timeout=120) as client:
                    with open(temp_path, "rb") as f:
                        response = await client.post(
                            "https://api.openai.com/v1/audio/transcriptions",
                            headers={"Authorization": f"Bearer {api_key}"},
                            data=data,
                            files={"file": (audio.filename or "asha-note.webm", f, content_type)},
                        )
                response.raise_for_status()
                transcript = response.json().get("text", "").strip()
                if transcript:
                    return {"text": transcript, "engine": "cloud", "language": language}
                errors.append("Cloud transcription returned an empty transcript")
            except Exception as exc:
                errors.append(f"Cloud transcription: {str(exc)[:240]}")

        try:
            transcript = _local_transcribe(temp_path, language)
            if transcript:
                return {"text": transcript, "engine": "offline", "language": language, "fallback_reason": errors or None}
            errors.append("Offline model returned an empty transcript")
        except Exception as exc:
            errors.append(str(exc))

        raise HTTPException(503, "No enhanced transcription engine is ready. " + " | ".join(errors) + " | Browser speech recognition may still be used as fallback.")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)

@app.post("/api/extract")
def extract(req: ExtractRequest):
    record = extract_record(req.note, req.beneficiary_id)
    matches = danger_check(req.note)
    return {"record": record, "danger_matches": matches, "needs_beneficiary_id": not bool(record["beneficiary_id"])}

@app.post("/api/validate")
def validate(req: ExtractRequest):
    return {"danger_matches": danger_check(req.note)}

@app.post("/api/visits")
def save_visit(req: ConfirmRequest):
    r = req.record
    if not r.beneficiary_id.strip():
        raise HTTPException(400, "Beneficiary ID is required.")
    if not r.confirmed:
        raise HTTPException(400, "The worker must confirm the read-back before saving.")
    matches = danger_check(r.original_note)
    visit_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute("""
        INSERT INTO visits
        (visit_id, beneficiary_id, visit_type, weight_kg, vaccination_status,
         vaccinations_due, next_visit_date, original_note, confirmed, danger_flag, danger_matches)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (
            visit_id, r.beneficiary_id, r.visit_type, r.weight_kg,
            r.vaccination_status, r.vaccinations_due, r.next_visit_date,
            r.original_note, 1 if matches else 0,
            json.dumps(matches, ensure_ascii=False)
        ))
        if r.next_visit_date:
            conn.execute("""
            INSERT INTO followups (task_id, visit_id, beneficiary_id, task_description, due_date, priority)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), visit_id, r.beneficiary_id,
                  "Next household visit", r.next_visit_date, "urgent" if matches else "normal"))
        if matches:
            conn.execute("""
            INSERT INTO followups (task_id, visit_id, beneficiary_id, task_description, due_date, priority)
            VALUES (?, ?, ?, ?, ?, 'urgent')
            """, (str(uuid.uuid4()), visit_id, r.beneficiary_id,
                  "Urgent PHC referral — follow the approved danger-sign protocol", date.today().isoformat()))
    return {"saved": True, "visit_id": visit_id, "danger_flag": bool(matches), "danger_matches": matches}

@app.get("/api/followups")
def followups():
    with db() as conn:
        rows = conn.execute("""
        SELECT task_id, beneficiary_id, task_description, due_date, priority, status
        FROM followups ORDER BY CASE priority WHEN 'urgent' THEN 0 ELSE 1 END, due_date
        """).fetchall()
    return {"items": [dict(x) for x in rows]}

@app.get("/api/visits")
def visits():
    with db() as conn:
        rows = conn.execute("SELECT * FROM visits ORDER BY created_at DESC LIMIT 100").fetchall()
    return {"items": [dict(x) for x in rows]}

app.mount("/", StaticFiles(directory=BASE / "frontend", html=True), name="frontend")
