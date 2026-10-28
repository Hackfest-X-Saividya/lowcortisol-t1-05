// One case file: details, witnesses (with consent), interview sessions, staff assignment.
// Starting a session shows the one-time witness code and opens the witness window.
import { useCallback, useEffect, useState } from "react";
import { Paper, InkButton } from "../../components/Paper.jsx";
import { ArrowGlyph } from "../../components/Glyph.jsx";
import { api, handOffWitnessToken } from "../../lib/api.js";
import { tilt } from "../../lib/rng.js";
import { linkProps } from "../../lib/router.js";
import Shell, { ErrorNote, fmtDate, useStaff } from "./Shell.jsx";

const LANGS = [
  ["kn", "Kannada"],
  ["hi", "Hindi"],
  ["en", "English"],
];

export function WitnessCode({ sessionId, code, onClose }) {
  const [copied, setCopied] = useState(false);
  return (
    <Paper seed={`code-${sessionId}`} rotate={-0.8} className="code-card" pins={[{ id: "code-pin", x: "50%" }]}>
      <h2 className="card-title ink">Witness code</h2>
      <p className="card-foot">Shown once. Give it only to the witness device. It stops working at sign-off.</p>
      <code className="code-value">{code}</code>
      <div className="btn-row">
        <InkButton
          variant="solid"
          glyph={<ArrowGlyph />}
          onClick={() => {
            handOffWitnessToken(sessionId, code);
            window.open(`/witness/${sessionId}`, "_blank", "noopener");
          }}
        >
          Open witness window
        </InkButton>
        <InkButton
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(code);
              setCopied(true);
            } catch {
              setCopied(false);
            }
          }}
        >
          {copied ? "Copied" : "Copy code"}
        </InkButton>
        {onClose && <InkButton onClick={onClose}>Done</InkButton>}
      </div>
    </Paper>
  );
}

export default function CaseFile({ id }) {
  const user = useStaff({ roles: ["officer", "supervisor", "artist"] });
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [wForm, setWForm] = useState({ display_name: "", preferred_language: "kn", consent_given: false, consent_note: "" });
  const [assign, setAssign] = useState({ user_id: "", role_on_case: "artist" });
  const [code, setCode] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api(`/cases/${id}`));
    } catch (e) {
      setError(e);
    }
  }, [id]);
  useEffect(() => {
    if (user) load();
  }, [user, load]);

  const act = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  if (!user) return null;
  const canWrite = user.role === "officer";
  return (
    <Shell title={data ? `Case ${data.case_number}` : "Case"} links={[["ring-lq1", "case-pin"], ["ring-rq1", "wit-pin"], ["ring-rq3", "sess-pin"]]}>
      <p className="crumbs">
        <a {...linkProps("/app/cases")}>Case files</a>
      </p>
      <ErrorNote error={error} />
      {data && (
        <div className="s-grid three">
          <section>
            <Paper seed={`case-card-${id}`} rotate={-0.6} pins={[{ id: "case-pin", x: "50%" }]} className="form-card">
              <h1 className="card-title ink">{data.case_number}</h1>
              <dl className="facts">
                <dt>Station</dt>
                <dd>{data.station}</dd>
                <dt>Crime type</dt>
                <dd>{data.crime_type || "unspecified"}</dd>
                <dt>Location</dt>
                <dd>{data.location_text || "not recorded"}</dd>
                <dt>Occurred</dt>
                <dd>{data.occurred_at ? fmtDate(data.occurred_at) : "not recorded"}</dd>
                <dt>Status</dt>
                <dd>{data.status}</dd>
              </dl>
              <h2 className="sub-title ink">Assigned</h2>
              <ul className="plain-list">
                {data.assignments.map((a) => (
                  <li key={a.user_id}>
                    <span className="typed">{a.role_on_case}</span> · <span className="mono-id">{a.user_id.slice(0, 8)}</span>
                  </li>
                ))}
              </ul>
              {canWrite && (
                <form
                  className="inline-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    act(() => api(`/cases/${id}/assignments`, { method: "POST", body: assign }));
                  }}
                >
                  <div className="field">
                    <label htmlFor="as-u">Staff user id</label>
                    <input id="as-u" value={assign.user_id} onChange={(e) => setAssign({ ...assign, user_id: e.target.value })} />
                  </div>
                  <div className="field">
                    <label htmlFor="as-r">Role on case</label>
                    <select id="as-r" value={assign.role_on_case} onChange={(e) => setAssign({ ...assign, role_on_case: e.target.value })}>
                      <option value="artist">artist</option>
                      <option value="assisting">assisting</option>
                      <option value="lead">lead</option>
                    </select>
                  </div>
                  <InkButton type="submit" disabled={busy || !assign.user_id.trim()}>
                    Assign
                  </InkButton>
                </form>
              )}
            </Paper>
          </section>

          <section>
            <Paper seed="wit-head" rotate={0.8} jag={2.4} className="section-strip" pins={[{ id: "wit-pin", x: "80%" }]}>
              <h2 className="ink">Witnesses</h2>
            </Paper>
            <ul className="note-list">
              {data.witnesses.map((w) => (
                <li key={w.id}>
                  <Paper seed={`w-${w.id}`} rotate={tilt(w.id, 1.3)} className="witness-note" pins={[{ x: "50%", tone: "ink" }]}>
                    <p className="note-title" lang={w.preferred_language}>
                      {w.display_name}
                    </p>
                    <p className="card-foot">
                      {LANGS.find(([k]) => k === w.preferred_language)?.[1]} · consent {w.consent_given ? "recorded" : "missing"}
                    </p>
                    {!w.consent_given && <span className="paper-stamp small">No consent</span>}
                    {canWrite && w.consent_given && (
                      <InkButton
                        disabled={busy}
                        onClick={() =>
                          act(async () => {
                            const s = await api(`/cases/${id}/sessions`, { method: "POST", body: { witness_id: w.id } });
                            setCode({ sessionId: s.session.id, code: s.witness_token });
                          })
                        }
                      >
                        Start session
                      </InkButton>
                    )}
                  </Paper>
                </li>
              ))}
            </ul>
            {canWrite && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  act(async () => {
                    await api(`/cases/${id}/witnesses`, { method: "POST", body: wForm });
                    setWForm({ display_name: "", preferred_language: "kn", consent_given: false, consent_note: "" });
                  });
                }}
              >
                <Paper seed="add-witness" rotate={-0.5} className="form-card">
                  <h3 className="sub-title ink">Add a witness</h3>
                  <div className="field">
                    <label htmlFor="wn">Name or reference</label>
                    <input id="wn" value={wForm.display_name} onChange={(e) => setWForm({ ...wForm, display_name: e.target.value })} required />
                  </div>
                  <div className="field">
                    <label htmlFor="wl">Language</label>
                    <select id="wl" value={wForm.preferred_language} onChange={(e) => setWForm({ ...wForm, preferred_language: e.target.value })}>
                      {LANGS.map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </div>
                  <label className="check">
                    <input type="checkbox" checked={wForm.consent_given} onChange={(e) => setWForm({ ...wForm, consent_given: e.target.checked })} />
                    Consent given by the witness
                  </label>
                  <div className="field">
                    <label htmlFor="wc">Consent note</label>
                    <input id="wc" value={wForm.consent_note} onChange={(e) => setWForm({ ...wForm, consent_note: e.target.value })} />
                  </div>
                  <InkButton type="submit" disabled={busy || !wForm.display_name.trim()}>
                    Add witness
                  </InkButton>
                </Paper>
              </form>
            )}
          </section>

          <section>
            <Paper seed="sess-head" rotate={-0.6} jag={2.4} className="section-strip" pins={[{ id: "sess-pin", x: "50%" }]}>
              <h2 className="ink">Interview sessions</h2>
            </Paper>
            {code && <WitnessCode sessionId={code.sessionId} code={code.code} onClose={() => setCode(null)} />}
            {data.session_ids.length === 0 && <p className="wall-note">No sessions yet. Start one from a witness note.</p>}
            <ul className="strip-list">
              {[...data.session_ids].reverse().map((sid) => (
                <li key={sid}>
                  <a className="strip-link" {...linkProps(`/app/sessions/${sid}`)}>
                    <Paper seed={`s-${sid}`} rotate={tilt(sid, 1.2)} jag={2.6} className="case-strip">
                      <span className="case-no ink">Session {sid.slice(0, 8)}</span>
                      <span className="case-meta">Open the session desk</span>
                    </Paper>
                  </a>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </Shell>
  );
}
