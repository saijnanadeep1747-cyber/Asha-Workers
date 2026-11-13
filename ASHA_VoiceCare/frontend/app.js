const $ = (id) => document.getElementById(id);
let recognition = null;
let mediaStream = null;
let mediaRecorder = null;
let recordedChunks = [];
let browserFallbackText = "";
let captureStartedAt = 0;
let currentDangerMatches = [];

async function api(path, options={}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Request failed");
  return data;
}
function setStatus(message){ $("micStatus").textContent = message; }
function getRecord(){
  return {
    beneficiary_id:$("beneficiary_id").value.trim(),
    visit_type:$("visit_type").value || null,
    weight_kg:$("weight_kg").value === "" ? null : Number($("weight_kg").value),
    vaccination_status:$("vaccination_status").value.trim() || null,
    vaccinations_due:$("vaccinations_due").value.trim() || null,
    next_visit_date:$("next_visit_date").value || null,
    original_note:$("note").value.trim(),
    confirmed:$("confirmed").checked
  };
}
function fillRecord(r){
  $("beneficiary_id").value = r.beneficiary_id || "";
  $("visit_type").value = r.visit_type || "";
  $("weight_kg").value = r.weight_kg ?? "";
  $("vaccination_status").value = r.vaccination_status || "";
  $("vaccinations_due").value = r.vaccinations_due || "";
  $("next_visit_date").value = r.next_visit_date || "";
  $("confirmed").checked = false;
  $("saveBtn").disabled = true;
}
function showDanger(matches){
  currentDangerMatches = matches || [];
  const box = $("dangerBox");
  if(!matches.length){box.classList.add("hidden");box.textContent="";return;}
  box.classList.remove("hidden");
  box.innerHTML = "<strong>⚠ Danger-sign match — urgent referral</strong><br>" +
    matches.map(m => `${escapeHtml(m.label)}: ${escapeHtml(m.referral_message)}`).join("<br>");
  speak(matches.map(m=>m.referral_message).join(". "));
}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}

function startRecognition(onText, append=true){
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR){alert("Speech recognition is not available in this browser. Try a supported Chromium-based browser, or type a test note.");return;}
  if(recognition){try{recognition.stop()}catch(e){}}
  recognition = new SR();
  recognition.lang = $("language").value;
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.onstart = ()=>setStatus("Listening… speak clearly");
  recognition.onerror = e=>setStatus("Speech recognition issue: " + e.error);
  recognition.onend = ()=>{setStatus("Microphone stopped");$("startBtn").disabled=false;$("stopBtn").disabled=true;};
  recognition.onresult = event => {
    let finalText = "";
    for(let i=event.resultIndex;i<event.results.length;i++){
      if(event.results[i].isFinal) finalText += event.results[i][0].transcript + " ";
    }
    if(finalText.trim()) onText(finalText.trim(), append);
  };
  recognition.start();
}
async function startHybridCapture(){
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setStatus("Audio recording is not supported here. Using browser speech recognition.");
    startRecognition((text)=>appendTranscript(text));
    return;
  }
  try {
    browserFallbackText = "";
    recordedChunks = [];
    const constraints = {audio:{echoCancellation:true, noiseSuppression:true, autoGainControl:true, channelCount:1}};
    mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
    const preferred = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
    const mimeType = preferred.find(t => MediaRecorder.isTypeSupported(t));
    mediaRecorder = new MediaRecorder(mediaStream, mimeType ? {mimeType} : undefined);
    mediaRecorder.ondataavailable = event => { if(event.data && event.data.size) recordedChunks.push(event.data); };
    mediaRecorder.onstop = async () => {
      $("startBtn").disabled=false; $("stopBtn").disabled=true;
      const blob = new Blob(recordedChunks, {type: mediaRecorder.mimeType || "audio/webm"});
      mediaStream?.getTracks().forEach(track=>track.stop());
      mediaStream = null;
      if (!blob.size) { setStatus("No audio captured. Check microphone permission and try again."); return; }
      setStatus("Enhancing and transcribing your recording…");
      try {
        const form = new FormData();
        form.append("audio", blob, "asha-note.webm");
        form.append("language", $("language").value);
        const response = await fetch("/api/transcribe", {method:"POST", body:form});
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Enhanced transcription unavailable");
        if (data.text) {
          appendTranscript(data.text);
          setStatus(`Transcribed using ${data.engine === "cloud" ? "cloud AI" : "offline AI"}. Please review every word.`);
          return;
        }
        throw new Error("Transcription returned no text");
      } catch (error) {
        if (browserFallbackText.trim()) {
          appendTranscript(browserFallbackText.trim());
          setStatus("Enhanced service unavailable; used browser fallback. Please check missing words.");
        } else {
          setStatus("Transcription unavailable: " + error.message + ". Check setup or type the note.");
        }
      }
    };
    mediaRecorder.start(1000);
    captureStartedAt = Date.now();
    setStatus("Recording with microphone noise suppression… speak in short phrases.");
    // Keep browser recognition in parallel as a fallback, not as the authoritative transcript.
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SR) {
      try {
        recognition = new SR();
        recognition.lang = $("language").value;
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.onresult = event => {
          let interim = "";
          for(let i=event.resultIndex;i<event.results.length;i++){
            const phrase = event.results[i][0].transcript;
            if(event.results[i].isFinal) browserFallbackText += phrase + " ";
            else interim += phrase;
          }
          if(interim) setStatus("Hearing (browser backup): " + interim);
        };
        recognition.onerror = () => {};
        recognition.start();
      } catch(e) { /* MediaRecorder path remains available. */ }
    }
  } catch(error) {
    setStatus("Microphone error: " + error.message + ". Allow microphone access and retry.");
    $("startBtn").disabled=false; $("stopBtn").disabled=true;
  }
}
function appendTranscript(text){
  if(!text) return;
  $("note").value += ($("note").value ? " " : "") + text;
  $("confirmed").checked=false; $("saveBtn").disabled=true;
}
$("startBtn").onclick = async ()=>{
  $("startBtn").disabled=true; $("stopBtn").disabled=false;
  await startHybridCapture();
};
$("stopBtn").onclick = ()=>{
  if(recognition){try{recognition.stop();}catch(e){} recognition=null;}
  if(mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
  else { $("startBtn").disabled=false; $("stopBtn").disabled=true; }
};
$("correctionBtn").onclick = ()=>{
  startRecognition((text)=>{
    const t=text.toLowerCase();
    const weight = t.match(/(?:weight|वजन|ತೂಕ)[^0-9]*(\d+(?:\.\d+)?)/i) || t.match(/(\d+(?:\.\d+)?)\s*(?:kilo|kg)/i);
    const id = t.match(/(?:beneficiary\s*id|id)[^a-z0-9]*([a-z0-9-]+)/i);
    if(weight) $("weight_kg").value=weight[1];
    else if(id) $("beneficiary_id").value=id[1];
    else if(t.includes("anc")) $("visit_type").value="ANC";
    else if(t.includes("pnc")) $("visit_type").value="PNC";
    else alert("I couldn't identify a supported correction. Please edit the field directly.");
    $("confirmed").checked=false;$("saveBtn").disabled=true;
    speak("Correction received. Please review the updated form.");
  },false);
};
$("extractBtn").onclick = async ()=>{
  const note=$("note").value.trim();
  if(!note){alert("Speak or enter a visit note first.");return;}
  try{
    const data=await api("/api/extract",{method:"POST",body:JSON.stringify({note})});
    fillRecord(data.record);showDanger(data.danger_matches);
    if(!data.record.beneficiary_id) alert("Beneficiary ID was not identified. Enter the synthetic beneficiary ID before saving.");
  }catch(e){alert(e.message);}
};
function speak(text){
  if(!("speechSynthesis" in window)){alert("Text-to-speech is unavailable in this browser.");return;}
  speechSynthesis.cancel();
  const utterance=new SpeechSynthesisUtterance(text);
  utterance.lang=$("language").value;
  speechSynthesis.speak(utterance);
}
$("readBtn").onclick=()=>{
  const r=getRecord();
  const speech=[
    `Beneficiary ID ${r.beneficiary_id || "not identified"}.`,
    `Visit type ${r.visit_type || "not identified"}.`,
    `Weight ${r.weight_kg===null?"not identified":r.weight_kg+" kilograms"}.`,
    `Vaccination status ${r.vaccination_status || "not specified"}.`,
    `Vaccinations or items mentioned ${r.vaccinations_due || "not specified"}.`,
    `Next visit date ${r.next_visit_date || "not specified"}.`,
    "Please check these details. Confirm only if they are correct."
  ].join(" ");
  speak(speech);
};
$("confirmed").onchange=()=>{$("saveBtn").disabled=!$("confirmed").checked;};
["beneficiary_id","visit_type","weight_kg","vaccination_status","vaccinations_due","next_visit_date"].forEach(id=>{
  $(id).addEventListener("input",()=>{$("confirmed").checked=false;$("saveBtn").disabled=true;});
  $(id).addEventListener("change",()=>{$("confirmed").checked=false;$("saveBtn").disabled=true;});
});
$("saveBtn").onclick=async()=>{
  const record=getRecord();
  if(!record.beneficiary_id){alert("Beneficiary ID is required.");return;}
  if(!record.confirmed){alert("Listen to the read-back and confirm first.");return;}
  if(!record.original_note){alert("Original visit note is missing.");return;}
  try{
    const result=await api("/api/visits",{method:"POST",body:JSON.stringify({record})});
    $("saveStatus").textContent="Visit saved. " + (result.danger_flag ? "Urgent danger-sign flag recorded." : "No configured danger sign matched.");
    $("saveStatus").style.color=result.danger_flag?"#a22b22":"#21634e";
    $("confirmed").checked=false;$("saveBtn").disabled=true;
    await loadFollowups();
  }catch(e){$("saveStatus").textContent=e.message;}
};
async function loadFollowups(){
  try{
    const data=await api("/api/followups");
    $("followups").innerHTML=data.items.length?data.items.map(x=>`
      <div class="followup"><div><strong>${escapeHtml(x.task_description)}</strong><br><small>ID: ${escapeHtml(x.beneficiary_id)} · Due: ${escapeHtml(x.due_date||"Not set")}</small></div>
      <span class="${x.priority==="urgent"?"urgent":"normal"}">${escapeHtml(x.priority)}</span></div>`).join(""):"<div class='empty'>No follow-ups yet. Save a confirmed visit to create one.</div>";
  }catch(e){$("followups").textContent="Could not load follow-ups: "+e.message;}
}
$("refreshBtn").onclick=loadFollowups;
(async()=>{
  try{await api("/api/health");$("apiStatus").textContent="● Backend connected";}catch(e){$("apiStatus").textContent="Backend not connected";}
  loadFollowups();
})();
