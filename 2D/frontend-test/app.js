/* Nishaan dummy test console: plain JS, no build step. */

const state = { access: null, refresh: null, user: null, blobs: {}, scene: null };
let ws = null;

const $ = (id) => document.getElementById(id);
const v = (id) => $(id).value.trim();
const show = (data) => { $("out").textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2); return data; };
function banner(msg, kind = "info") { const b = $("banner"); b.textContent = msg; b.className = `banner ${kind}`; }
class UserError extends Error {}
// Throw a readable message when a required field is empty.
function need(id, hint) {
  if (!v(id)) { banner(hint, "error"); throw new UserError(hint); }
  return v(id);
}
function needSession() {
  return need("sessionId", "No session id. Complete step 2 (create case -> add witness -> start session) or paste an existing session id.");
}
function needLogin() {
  if (!state.access && !($("actor").value === "witness" && v("witnessToken"))) {
    const m = "Not logged in. Log in as a staff user first (step 1), or switch 'Act as' to witness and paste a witness token.";
    banner(m, "error"); throw new UserError(m);
  }
}
window.addEventListener("unhandledrejection", (e) => {
  if (!(e.reason instanceof UserError)) banner(`Error: ${e.reason?.message || e.reason}`, "error");
  e.preventDefault();
});
const log = (msg) => { const el = $("log"); el.textContent = `${new Date().toLocaleTimeString()} ${msg}\n` + el.textContent; };

function token() {
  if ($("actor").value === "witness") return v("witnessToken");
  return state.access;
}

function headers(extra = {}) {
  const h = { ...extra };
  const t = token();
  if (t) h["Authorization"] = `Bearer ${t}`;
  return h;
}

async function api(method, path, body, raw = false) {
  const opts = { method, headers: headers(body && !(body instanceof FormData) ? { "Content-Type": "application/json" } : {}) };
  if (body) opts.body = body instanceof FormData ? body : JSON.stringify(body);
  let r;
  try {
    r = await fetch(v("apiBase") + path, opts);
  } catch (e) {
    show(`network error: ${e.message} (is the backend running and CORS_ORIGINS including this origin?)`);
    throw e;
  }
  if (raw) return r;
  const text = await r.text();
  let data;
  try { data = JSON.parse(text); } catch { data = text; }
  if (!r.ok) {
    show({ status: r.status, ...((data && data.error) ? data : { body: data }) });
    let msg = data && data.error ? `${data.error.code}: ${data.error.message}` : `HTTP ${r.status}`;
    if (r.status === 422 && data?.error?.details?.errors) {
      msg += " - " + data.error.details.errors.map((x) => `${x.loc.slice(-1)[0]} ${x.msg}`).join("; ");
    }
    if (r.status === 401) msg += " (log in again, or check the witness token / 'Act as')";
    banner(`${method} ${path} -> ${msg}`, "error");
    throw new Error(msg);
  }
  banner(`${method} ${path} -> ${r.status} OK`, "success");
  return data;
}

async function waitJob(jobId) {
  for (let i = 0; i < 600; i++) {
    const j = await api("GET", `/jobs/${jobId}`);
    if (j.status === "done") return j.result;
    if (j.status === "failed") { show(j); throw new Error(j.error); }
    await new Promise((res) => setTimeout(res, 700));
  }
  throw new Error("job timeout");
}

async function fileUrl(fileId) {
  if (state.blobs[fileId]) return state.blobs[fileId];
  const r = await api("GET", `/files/${fileId}`, null, true);
  if (!r.ok) { show(await r.text()); throw new Error(`file ${r.status}`); }
  const url = URL.createObjectURL(await r.blob());
  state.blobs[fileId] = url;
  return url;
}

// ---- 1. auth ------------------------------------------------------------------------------
async function login() {
  need("username", "Enter a username (for example officer1).");
  need("password", "Enter the password printed by python -m app.seed.seed.");
  const d = await api("POST", "/auth/login", { username: v("username"), password: v("password") });
  banner(`Logged in as ${d.user.username} (${d.user.role}). Step 2: create a case, add a witness, start a session.`, "success");
  state.access = d.access_token; state.refresh = d.refresh_token; state.user = d.user;
  $("whoami").textContent = `${d.user.username} (${d.user.role})`;
  $("actor").value = "staff";
  show(d.user);
  loadCatalogs();
}

async function refreshReady() {
  try {
    const r = await fetch(v("apiBase") + "/ready");
    const d = await r.json();
    $("ready").textContent = `${d.status} · ${d.ai_mode} · ${d.data_mode}`;
    $("ready").className = "pill " + (d.status === "ready" ? "ok" : "bad");
  } catch { $("ready").textContent = "backend unreachable"; $("ready").className = "pill bad"; }
}

// ---- 2. case / witness / session ----------------------------------------------------------
async function createCase() {
  needLogin();
  const num = v("caseNumber") || `CR-${Date.now().toString().slice(-6)}`;
  const d = await api("POST", "/cases", { case_number: num, crime_type: v("crimeType"), location_text: "test" });
  $("caseId").value = d.id; show(d);
}
async function addWitness() {
  needLogin(); need("caseId", "Create a case first (or paste a case id).");
  const d = await api("POST", `/cases/${v("caseId")}/witnesses`, {
    display_name: v("witnessName"), preferred_language: $("witnessLang").value,
    consent_given: $("consent").checked, consent_note: "test console",
  });
  $("witnessId").value = d.id; show(d);
}
async function startSession() {
  needLogin(); need("caseId", "Create a case first."); need("witnessId", "Add a witness first (consent must be ticked).");
  const d = await api("POST", `/cases/${v("caseId")}/sessions`, { witness_id: v("witnessId") });
  $("sessionId").value = d.session.id; $("witnessToken").value = d.witness_token;
  show(d); connectWs();
  banner("Session started and witness token stored. Step 3: submit the free-recall statement (required before the interview and the first face).", "success");
}

// ---- 3. statements -----------------------------------------------------------------------
async function submitText() {
  needLogin(); needSession(); need("statementText", "Type the statement text first.");
  const d = await api("POST", `/sessions/${v("sessionId")}/statements`, {
    text: v("statementText"), language: $("stLang").value, kind: $("stKind").value,
    source: $("stSource").value, target_version_id: $("stKind").value.endsWith("_command") ? (v("versionId") || v("sceneVersionId")) : null,
  });
  show(d); const res = await waitJob(d.job_id); show(res);
  const sheet = await api("GET", `/sessions/${v("sessionId")}/feature-sheet`); renderSheet(sheet.sheet);
}
async function submitAudio(blob) {
  needLogin(); needSession();
  const file = blob || $("audioFile").files[0];
  if (!file) return show("choose an audio file first");
  const fd = new FormData();
  fd.append("audio", file, file.name || "recording.webm");
  fd.append("language", $("stLang").value); fd.append("kind", $("stKind").value);
  if ($("stKind").value.endsWith("_command")) fd.append("target_version_id", v("versionId") || v("sceneVersionId"));
  const d = await api("POST", `/sessions/${v("sessionId")}/statements`, fd);
  show(d); show(await waitJob(d.job_id));
}
let recorder = null, chunks = [];
async function recordToggle() {
  if (recorder) { recorder.stop(); return; }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  chunks = []; recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
  recorder.ondataavailable = (e) => chunks.push(e.data);
  recorder.onstop = () => { stream.getTracks().forEach((t) => t.stop()); recorder = null; $("recBtn").textContent = "Record mic";
    submitAudio(new File(chunks, "recording.webm", { type: "audio/webm" })); };
  recorder.start(); $("recBtn").textContent = "Stop + send";
}
function renderSheet(sheet) {
  const rows = Object.entries(sheet || {}).map(([k, e]) => `<tr><td>${k}</td><td>${e.value}</td><td>${e.confidence}</td><td>${(e.source_text || "").slice(0, 60)}</td></tr>`).join("");
  $("sheet").innerHTML = rows ? `<table><tr><th>field</th><th>value</th><th>conf</th><th>source</th></tr>${rows}</table>` : "<em>empty</em>";
}

// ---- 4. interview --------------------------------------------------------------------------
async function nextQuestion() {
  needLogin(); needSession();
  const d = await api("GET", `/sessions/${v("sessionId")}/questions/next`); show(d);
  if (d.done) { $("question").innerHTML = `<b>Interview done (${d.reason})</b>`; return; }
  const q = d.question;
  const opts = q.options.map((o) => `<button class="secondary" onclick="answer('${q.id}','option','${o.id}')">${o.label}</button>`).join("");
  $("question").innerHTML = `<p><b>${q.field_key}</b> [${q.stage}]<br>${q.text_en}<br><i>${q.text_local}</i></p>
    <div class="row">${opts}</div>
    <div class="row"><input id="answerText" placeholder="free text answer" size="40">
    <button onclick="answer('${q.id}','text')">Answer text</button>
    <button class="secondary" onclick="answer('${q.id}','skipped')">Skip</button></div>`;
}
async function answer(qid, type, optionId) {
  const body = { answer_type: optionId === "not_remembered" ? "not_remembered" : type };
  if (type === "option") body.option_id = optionId;
  if (type === "text") { body.text = $("answerText").value; body.language = $("witnessLang").value; }
  show(await api("POST", `/sessions/${v("sessionId")}/questions/${qid}/answer`, body));
  await nextQuestion();
}

// ---- 5. sketch ------------------------------------------------------------------------------
async function loadCatalogs() {
  try {
    const c = await api("GET", "/sketch-controls");
    $("sliderParam").innerHTML = c.sliders.map((s) => `<option value="${s.name}">${s.name} (${s.region})</option>`).join("");
    const o = await api("GET", "/overlays");
    $("overlayId").innerHTML = o.map((x) => `<option value="${x.id}">${x.name} [${x.region}]</option>`).join("");
  } catch (e) { /* catalogs need a login */ }
}
async function generateSketch() {
  needLogin(); needSession();
  const d = await api("POST", `/sessions/${v("sessionId")}/sketch`, {}); show(d);
  const res = await waitJob(d.job_id); show(res);
  $("versionId").value = res.version_id; await loadTree(); await loadVersion();
}
async function loadTree() {
  needSession();
  const t = await api("GET", `/sessions/${v("sessionId")}/sketch-tree`);
  const cur = v("versionId");
  $("tree").innerHTML = t.map((n) => `<button class="${n.id === cur ? "sel" : "secondary"}" title="${n.id}" onclick="$('versionId').value='${n.id}';loadVersion()">
    ${n.edit_source}${n.edit_type ? ":" + n.edit_type : ""}${n.parent_id ? " ← " + n.parent_id.slice(0, 4) : ""} (${n.id.slice(0, 4)})${n.witness_rating ? " ★" + n.witness_rating : ""}${n.stability_warning ? " ⚠" : ""}</button>`).join(" ");
}
async function loadVersion() {
  need("versionId", "Generate the first face (or pick a version in the tree) first.");
  const d = await api("GET", `/sketch-versions/${v("versionId")}`); show(d);
  $("sketchImg").src = await fileUrl(d.sketch_file_id);
  await loadLocks(); await loadTree();
}
async function recordDisplay() {
  show(await api("POST", `/sessions/${v("sessionId")}/display-events`, { sketch_version_id: v("versionId"), screen: "witness" }));
}
async function rate(r) { show(await api("POST", `/sketch-versions/${v("versionId")}/rating`, { rating: r })); loadTree(); }

let busy = false;
async function runEdit(body) {
  needLogin(); need("versionId", "Generate the first face first; edits apply to a sketch version.");
  if (busy) return show("an edit is still running; wait for it to finish");
  busy = true; document.body.style.cursor = "progress";
  try {
    const d = await api("POST", `/sketch-versions/${v("versionId")}/edits`, body); show(d);
    const res = await waitJob(d.job_id); show(res);
    if (res.status === "created") { $("versionId").value = res.new_version_id; await loadVersion(); }
    else if (res.status === "needs_choice") { await renderPreviews(res.previews, body); }
    else { log(`edit ${res.status}: ${res.message}`); alert(res.message); }
    return res;
  } finally { busy = false; document.body.style.cursor = ""; }
}
function editUtterance() { return runEdit({ source: "voice", utterance_original: v("utterance"), language: $("editLang").value }); }
function editSlider() { return runEdit({ source: "slider", edit: { param: $("sliderParam").value, amount: parseFloat($("sliderAmount").value) } }); }
function editOverlay(remove) {
  const params = { size: 1.0 }; if ($("overlayPos").value) params.position = $("overlayPos").value; if (remove) params.remove = true;
  return runEdit({ source: "accessory", edit: { type: "overlay", overlay_id: $("overlayId").value, overlay_params: params } });
}
function editInpaint() { return runEdit({ source: "text", edit: { type: "inpaint", region: $("inpaintRegion").value, prompt: v("inpaintPrompt") } }); }
async function previews() {
  needLogin(); need("versionId", "Generate the first face first.");
  const body = { source: "slider", edit: { param: $("sliderParam").value } };
  const d = await api("POST", `/sketch-versions/${v("versionId")}/previews`, body);
  const res = await waitJob(d.job_id); show(res); await renderPreviews(res.previews, body);
}
async function renderPreviews(list, body) {
  const el = $("previews"); el.innerHTML = "";
  for (const p of list) {
    const img = document.createElement("img"); img.src = await fileUrl(p.sketch_file_id); img.title = `amount ${p.amount}: click to apply`;
    img.onclick = () => runEdit({ source: "slider", edit: { param: body.edit?.param || body.param, amount: p.amount } });
    el.appendChild(img);
  }
}
async function loadLocks() {
  const locks = await api("GET", `/sessions/${v("sessionId")}/locks`);
  $("locks").innerHTML = "Locks: " + locks.map((l) => `<label><input type="checkbox" ${l.locked ? "checked" : ""} onchange="setLock('${l.feature}', this.checked)"> ${l.feature}${l.confidence ? " (" + l.confidence + ")" : ""}</label>`).join(" ");
}
async function setLock(feature, locked) {
  show(await api("PUT", `/sessions/${v("sessionId")}/locks`, { locks: [{ feature, locked }] }));
}
async function compare() { show(await api("GET", `/sketch-versions/${v("versionId")}/compare/${v("compareId")}`)); }

// ---- 6. scene -----------------------------------------------------------------------------------
async function buildScene() {
  needLogin(); needSession();
  const body = $("sceneTemplate").value ? { template: $("sceneTemplate").value } : {};
  const d = await api("POST", `/sessions/${v("sessionId")}/scene`, body); show(d);
  const res = await waitJob(d.job_id); show(res); $("sceneVersionId").value = res.version_id; await loadScene();
}
async function loadSceneTree() { show(await api("GET", `/sessions/${v("sessionId")}/scene-tree`)); }
async function loadScene() {
  need("sceneVersionId", "Build the scene first.");
  const d = await api("GET", `/scene-versions/${v("sceneVersionId")}`); show(d); state.scene = d.scene;
  $("sceneAnalysis").innerHTML = `distance <b>${d.analysis.distance_m}</b> m, line of sight <b>${d.analysis.line_of_sight}</b>${d.analysis.blocking_object_id ? " (blocked by " + d.analysis.blocking_object_id + ")" : ""}`;
  drawScene(d.scene);
}
function drawScene(s) {
  const c = $("sceneCanvas"), ctx = c.getContext("2d");
  ctx.clearRect(0, 0, c.width, c.height);
  const pad = 20, k = Math.min((c.width - 2 * pad) / s.room.width_m, (c.height - 2 * pad) / s.room.depth_m);
  const P = (x, z) => [pad + x * k, pad + z * k];
  ctx.strokeStyle = "#333"; ctx.strokeRect(pad, pad, s.room.width_m * k, s.room.depth_m * k);
  for (const o of s.objects) {
    ctx.save(); const [cx, cz] = P(o.pos[0], o.pos[2]); ctx.translate(cx, cz); ctx.rotate((o.rot_y_deg * Math.PI) / 180);
    ctx.fillStyle = o.type === "road" ? "#ddd" : "#9cc3e6"; ctx.fillRect(-o.size[0] * k / 2, -o.size[2] * k / 2, o.size[0] * k, o.size[2] * k);
    ctx.restore(); ctx.fillStyle = "#222"; ctx.font = "10px sans-serif"; ctx.fillText(o.id + (o.locked ? " 🔒" : ""), cx - 15, cz);
  }
  for (const p of s.people) {
    const [x, z] = P(p.pos[0], p.pos[2]); ctx.fillStyle = p.role === "witness" ? "#16a34a" : p.role === "suspect" ? "#dc2626" : "#a16207";
    ctx.beginPath(); ctx.arc(x, z, 6, 0, 7); ctx.fill(); ctx.fillText(p.id, x + 8, z + 3);
    const r = (p.facing_deg * Math.PI) / 180; ctx.beginPath(); ctx.moveTo(x, z); ctx.lineTo(x + 14 * Math.sin(r), z - 14 * Math.cos(r)); ctx.strokeStyle = ctx.fillStyle; ctx.stroke();
  }
  for (const e of s.evidence) { const [x, z] = P(e.pos[0], e.pos[2]); ctx.fillStyle = "#f59e0b"; ctx.fillText("▲ " + e.label, x - 4, z); }
}
async function applyPatch() {
  const d = await api("POST", `/scene-versions/${v("sceneVersionId")}/patches`, { patch: JSON.parse(v("patch")), source: "drag" });
  show(d); $("sceneVersionId").value = d.id; await loadScene();
}
async function sceneCommand() {
  const d = await api("POST", `/scene-versions/${v("sceneVersionId")}/commands`, { utterance_original: v("sceneCmd"), language: $("sceneLang").value });
  const res = await waitJob(d.job_id); show(res);
  if (res.version_id) { $("sceneVersionId").value = res.version_id; await loadScene(); }
}

// ---- 7. signoff / exports --------------------------------------------------------------------------
async function signoff() {
  needLogin(); needSession();
  show(await api("POST", `/sessions/${v("sessionId")}/signoff`, {
    sketch_version_id: v("versionId") || null, scene_version_id: v("sceneVersionId") || null,
    confidences: JSON.parse(v("confidences")), witness_statement: v("witnessStatement"),
  }));
}
async function doExport() {
  needLogin(); needSession();
  const d = await api("POST", `/sessions/${v("sessionId")}/exports`, { kind: $("exportKind").value }); show(d);
  const res = await waitJob(d.job_id); show(res);
  const url = await fileUrl(res.file_id);
  const a = document.createElement("a"); a.href = url; a.download = `${res.kind}-${res.export_id.slice(0, 8)}.${res.kind === "pdf" ? "pdf" : "png"}`; a.textContent = `download ${res.kind} `;
  $("exportLinks").appendChild(a);
}

// ---- websocket -------------------------------------------------------------------------------------
function connectWs() {
  if (!v("sessionId")) return show("start a session first");
  if (ws) ws.close();
  const base = v("apiBase").replace(/^http/, "ws").replace(/\/api\/v1\/?$/, "");
  const t = token(); if (!t) return show("login or witness token needed for the WebSocket");
  ws = new WebSocket(`${base}/ws/sessions/${v("sessionId")}?token=${encodeURIComponent(t)}`);
  ws.onopen = () => { $("wsState").textContent = "open"; $("wsState").className = "pill ok"; };
  ws.onclose = (e) => { $("wsState").textContent = `closed ${e.code}`; $("wsState").className = "pill bad"; };
  ws.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    log(`${ev.type} ${ev.data ? JSON.stringify(ev.data).slice(0, 160) : ""}`);
    if (ev.type === "version.created") loadTree().catch(() => {});
  };
}

refreshReady(); setInterval(refreshReady, 15000);
