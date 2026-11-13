# ASHA VoiceCare — Voice Field Register Prototype

A hackathon-ready starter prototype that turns a spoken home-visit note into a reviewable structured record, reads it back, requires worker confirmation before saving, checks a small configurable danger-sign list, and creates follow-up tasks.

## Important scope and safety notes

- This is a **prototype**, not a clinically validated product and not an official government health-record system.
- Use **synthetic beneficiaries only**. Do not enter real names, phone numbers, addresses, Aadhaar numbers, or patient records.
- The danger-sign rules are intentionally small and phrase-based. They are not comprehensive. A phrase not matching the configured list will not be flagged.
- The app does not diagnose or recommend treatment. A match produces an urgent PHC referral message only.
- Hybrid speech capture records microphone audio with browser echo cancellation, noise suppression and automatic gain control. On Stop, the backend tries OpenAI cloud transcription (if configured), then the optional local faster-whisper model, while browser Web Speech runs as a last-resort fallback. This improves capture but cannot guarantee perfect recognition in heavy noise. Always review the transcript.
- Before any real-world use, obtain clinical/public-health review, privacy/security review, field validation, and approval from the relevant health authority.

## Features

1. Voice capture using browser speech recognition where supported.
2. Language selector for Kannada, Hindi, English (India), Tamil, Telugu, Malayalam, Marathi and Bengali. Availability depends on browser support.
3. Basic extraction of beneficiary ID, visit type, weight, vaccination wording and numeric next-visit date.
4. Form read-back using browser text-to-speech.
5. Voice correction for a spoken weight or beneficiary ID, with manual editing available.
6. Confirmation checkbox required before save.
7. Configurable phrase-list danger checks and urgent PHC referral flag.
8. SQLite visit and follow-up storage.
9. Synthetic demo beneficiary file.

## Requirements

- Python 3.10+
- A modern browser. Speech recognition is commonly available in Chromium-based browsers, but support varies.
- Internet may be required by the browser's speech recognition service.

## Run locally

From this folder:

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install and run:

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Open: http://127.0.0.1:8000

API health check: http://127.0.0.1:8000/api/health

## Demo script

Try this note in the text area or dictate it:

`Beneficiary ID SYN-1001, ANC checkup today, weight 52 kilo, TT injection completed, next visit 05/12/2026.`

Click **Extract visit details**, review every field, click **Read form aloud**, tick the confirmation checkbox, then save.

Try the correction button and say:

`No, weight is 2.8 kilo.`

For danger-sign testing, try:

`Beneficiary ID SYN-1002, newborn has high fever.`

The demo should show an urgent referral warning. Test pregnancy bleeding with:

`Beneficiary ID SYN-1001, bleeding during pregnancy.`

## Danger-sign list and references

The included `data/danger_signs.json` contains only two starter phrases:
- Bleeding during pregnancy
- High fever in a newborn

Reference materials to consult, verify against the currently applicable Indian programme guidance, and cite in your final submission:
- Government of India, Ministry of Health and Family Welfare, **Mother and Child Protection (MCP) Card**: https://nhm.gov.in/images/pdf/programmes/maternal-health/guidelines/MCP_Card.pdf
- World Health Organization, **WHO recommendations for care of the preterm or low-birth-weight infant** and newborn danger-sign guidance: https://www.who.int/health-topics/newborn-health

Do not treat this prototype phrase list as a substitute for the complete official referral protocol. Confirm the exact fever threshold, age range, local wording, and referral pathway with the public-health guideline selected by your team and your mentor. Add exact page/section references to this README before submission.

## API endpoints

- `GET /api/health`
- `POST /api/extract`
- `POST /api/validate`
- `POST /api/visits`
- `GET /api/visits`
- `GET /api/followups`

## Project structure

```text
asha_voicecare/
├── backend/
│   ├── main.py
│   └── __init__.py
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── data/
│   ├── danger_signs.json
│   └── synthetic_beneficiaries.json
├── tests/
│   └── test_rules.py
├── requirements.txt
└── README.md
```

## Current limitations / next development steps

- Replace the browser speech API with a validated streaming Indic STT engine for reliable code-mix and field noise.
- Add audio preprocessing, voice activity detection, confidence scores and a repeat/clarify flow.
- Expand extraction with a tested Indic-English medical vocabulary and explicit field-level confidence.
- Parse natural-language dates carefully; current extraction only recognises numeric dates.
- Make corrections field-aware in every supported language and read back the corrected field.
- Add secure authentication, encryption at rest, audit logs, retention controls and consent before any real deployment.
- Add tests using recorded, consented, de-identified test audio and measure field-level accuracy and danger-sign recall separately.


## Hybrid Kannada speech recognition upgrade

### What it does
- Captures audio from the existing laptop/mobile microphone using `echoCancellation`, `noiseSuppression`, `autoGainControl` and mono capture where supported by the browser/device.
- Keeps browser Web Speech recognition running as a fallback.
- On Stop, uploads the recorded clip to the backend. The backend tries OpenAI `gpt-transcribe` when `OPENAI_API_KEY` is configured, then local faster-whisper if installed. If both are unavailable, the UI uses the browser transcript.
- The Kannada hint includes common ASHA/medical terms. Hints are not forced into the transcript; verify all names, numbers, dates, weights and clinical details manually.

### Install on Windows (Git Bash or VS Code terminal)
Run these commands from the `ASHA_VoiceCare` project root (the folder containing `requirements.txt`):

```bash
# Activate your existing environment if it is not already active
source .venv/Scripts/activate

# Install backend and audio-upload dependencies
pip install -r requirements.txt

# Install the offline fallback (recommended if internet is unreliable)
pip install -r requirements-voice.txt
```

The first offline transcription downloads the Whisper model. `small` is the default CPU model and may be slow on older laptops. You can choose `base` for lower resource use or `medium`/`large-v3` for potentially better accuracy at higher memory and speed cost by editing `ASHA_WHISPER_MODEL` in `.env`.

### Optional cloud setup
1. Copy `.env.example` to a new file named `.env` in the project root.
2. Put your own API key after `OPENAI_API_KEY=`. Do not share it, commit it, or put it in `frontend/app.js`.
3. Keep `ASHA_CLOUD_STT_MODEL=gpt-transcribe`. The backend will attempt cloud first and fall back to offline if cloud fails.
4. Cloud transcription incurs API charges and sends recorded audio to the configured provider. Use synthetic/demo audio unless your organisation has approved the privacy, consent, security and data-processing arrangements for real health information.

### Run
```bash
python -m uvicorn backend.main:app --reload
```
Open http://127.0.0.1:8000, select Kannada, click Start speaking, speak a short phrase, then click Stop. The final enhanced transcript is added to the note. Wait for the status message and review it before Extract / Save.

### Troubleshooting
- Allow microphone access in the browser site settings; use localhost/127.0.0.1 or HTTPS.
- If the browser reports no microphone, check Windows Settings > Privacy & security > Microphone and close other apps using the microphone.
- If cloud is not configured, offline recognition requires `pip install -r requirements-voice.txt`; first run downloads the model and needs internet.
- If neither AI engine is installed/configured, the app falls back to browser speech recognition. It will show a warning in the status line.
- `noiseSuppression`, `echoCancellation` and `autoGainControl` depend on browser and microphone hardware; they do not remove every kind of noise. A close-positioned headset mic usually helps more than software alone.
- Do not silently autocorrect clinical words, danger signs, medication names, numbers or dates. Always have the ASHA worker verify the transcript and extracted fields before saving.

### API
- `POST /api/transcribe` accepts multipart fields `audio` and `language` and returns `{text, engine, language}`.
