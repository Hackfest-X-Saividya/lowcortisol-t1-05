// Session desk: the officer's view of one interview session. Left: index strips. Centre:
// the selected file pinned to the wall. Live updates arrive over the session WebSocket.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Paper, InkButton } from "../../components/Paper.jsx";
import AuthImage from "../../components/AuthImage.jsx";
import SceneMap from "../../components/SceneMap.jsx";
import { api, auth, fileUrl, runJob, sessionEvents } from "../../lib/api.js";
import { tilt } from "../../lib/rng.js";
import { linkProps } from "../../lib/router.js";
import Shell, { ErrorNote, fmtDate, useStaff } from "./Shell.jsx";
import { WitnessCode } from "./CaseFile.jsx";

const TABS = [
  ["summary", "Summary"],
  ["statements", "Statements"],
  ["interview", "Interview"],
  ["sheet", "Feature sheet"],
  ["sketch", "Sketch"],
  ["scene", "Scene"],
  ["exports", "Exports"],
  ["audit", "Audit log"],
];

export default function SessionDesk({ id }) {
  const user = useStaff({ roles: ["officer", "supervisor", "artist"] });
  const [tab, setTab] = useState("summary");
  const [session, setSession] = useState(null);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  const [events, setEvents] = useState([]);
  const refresh = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    if (!user) return;
    api(`/sessions/${id}`)
      .then(setSession)
      .catch(setError);
  }, [user, id, tick]);

  useEffect(() => {
    if (!user || !auth.access) return undefined;
    return sessionEvents(id, auth.access, (ev) => {
      if (ev.type === "connected" || ev.type === "pong") return;
      setEvents((list) => [ev, ...list].slice(0, 40));
      if (["version.created", "feature_sheet.updated", "scene.updated", "export.ready", "question.next", "statement.transcribed"].includes(ev.type)) refresh();
    });
  }, [user, id, refresh]);

  if (!user) return null;
  return (
    <Shell title={`Session ${id.slice(0, 8)}`} stamp={session?.status === "paused" ? "Session paused" : "Staff view"} links={[["ring-lq1", "desk-idx"], ["ring-tma", "desk-file"]]}>
      <p className="crumbs">
        <a {...linkProps("/app/cases")}>Case files</a>
        {session && (
          <>
            {" / "}
            <a {...linkProps(`/app/cases/${session.case_id}`)}>Case file</a>
          </>
        )}
      </p>
      <ErrorNote error={error} />
      <div className="desk">
        <nav className="desk-index" aria-label="Session index">
          <Paper seed="desk-idx" rotate={-0.8} jag={2.4} className="section-strip" pins={[{ id: "desk-idx", x: "22%" }]}>
            <span className="ink">Session {id.slice(0, 8)}</span>
          </Paper>
          <ul className="idx-list">
            {TABS.map(([k, label], i) => (
              <li key={k}>
                <Paper
                  seed={`desk-${k}`}
                  rotate={tilt(`desk-${k}`, 1.3)}
                  jag={2.5}
                  className={`menu-strip ${tab === k ? "is-selected" : ""}`}
                  style={{ width: `${86 + ((i * 5) % 14)}%` }}
                  pins={tab === k ? [{ x: "10%" }] : []}
                >
                  <button type="button" className="menu-btn" aria-current={tab === k ? "page" : undefined} onClick={() => setTab(k)}>
                    <span className="ink">{label}</span>
                  </button>
                </Paper>
              </li>
            ))}
          </ul>
          {events.length > 0 && (
            <Paper seed="events" rotate={1} className="events-card">
              <h3 className="sub-title ink">Live</h3>
              <ul className="plain-list small">
                {events.slice(0, 6).map((e, i) => (
                  <li key={i}>
                    <span className="typed">{e.type}</span>
                  </li>
                ))}
              </ul>
            </Paper>
          )}
        </nav>
        <section className="desk-file">
          <Paper seed={`file-${tab}`} rotate={0} className="desk-sheet" pins={[{ id: "desk-file", x: "50%" }]}>
            {session && tab === "summary" && <Summary session={session} user={user} onChange={refresh} />}
            {session && tab === "statements" && <Statements sid={id} tick={tick} active={session.status === "active"} onChange={refresh} />}
            {session && tab === "interview" && <Interview sid={id} tick={tick} />}
            {session && tab === "sheet" && <Sheet sid={id} tick={tick} />}
            {session && tab === "sketch" && <Sketch sid={id} tick={tick} user={user} />}
            {session && tab === "scene" && <Scene session={session} tick={tick} />}
            {session && tab === "exports" && <Exports sid={id} user={user} />}
            {session && tab === "audit" && <Audit sid={id} user={user} />}
          </Paper>
        </section>
      </div>
    </Shell>
  );
}

function Summary({ session, user, onChange }) {
  const [code, setCode] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const act = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChange();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const open = session.status === "active" || session.status === "paused";
  return (
    <div className="file-body">
      <h1 className="card-title ink">Session summary</h1>
      <dl className="facts">
        <dt>Status</dt>
        <dd>{session.status}</dd>
        <dt>Started</dt>
        <dd>{fmtDate(session.started_at)}</dd>
        <dt>Witness language</dt>
        <dd>{session.preferred_language}</dd>
        <dt>Free recall</dt>
        <dd>{session.has_free_recall ? "saved" : "not yet"}</dd>
        <dt>Questions asked</dt>
        <dd>{session.question_count}</dd>
        <dt>First image shown</dt>
        <dd>{session.first_image_shown_at ? fmtDate(session.first_image_shown_at) : "not yet"}</dd>
        <dt>Locked features</dt>
        <dd>
          {Object.entries(session.locks || {})
            .filter(([, v]) => v.locked)
            .map(([k]) => k)
            .join(", ") || "none"}
        </dd>
      </dl>
      <ErrorNote error={error} />
      {user.role === "officer" && (
        <div className="btn-row">
          {session.status === "active" && (
            <InkButton disabled={busy} onClick={() => act(() => api(`/sessions/${session.id}/pause`, { method: "POST" }))}>
              Pause session
            </InkButton>
          )}
          {session.status === "paused" && (
            <InkButton disabled={busy} onClick={() => act(() => api(`/sessions/${session.id}/resume`, { method: "POST" }))}>
              Resume session
            </InkButton>
          )}
          {open && (
            <InkButton
              disabled={busy}
              onClick={() =>
                act(async () => {
                  const r = await api(`/sessions/${session.id}/witness-token`, { method: "POST" });
                  setCode(r.witness_token);
                })
              }
            >
              New witness code
            </InkButton>
          )}
          {session.status !== "closed" && (
            <InkButton disabled={busy} onClick={() => act(() => api(`/sessions/${session.id}/close`, { method: "POST" }))}>
              Close session
            </InkButton>
          )}
        </div>
      )}
      {code && <WitnessCode sessionId={session.id} code={code} onClose={() => setCode(null)} />}
    </div>
  );
}

function Statements({ sid, tick, active, onChange }) {
  const [rows, setRows] = useState([]);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    api(`/sessions/${sid}/statements`).then(setRows).catch(setError);
  }, [sid, tick]);
  const save = async () => {
    try {
      await runJob(`/sessions/${sid}/statements/${editing.id}`, { method: "PATCH", body: { corrected_transcript_original: editing.text, note: editing.note || "" } });
      setEditing(null);
      onChange();
    } catch (e) {
      setError(e);
    }
  };
  return (
    <div className="file-body">
      <h1 className="card-title ink">Statements</h1>
      <ErrorNote error={error} />
      {rows.length === 0 && <p>No statements yet.</p>}
      {rows.map((s) => (
        <article key={s.id} className="record">
          <p className="record-meta typed">
            {s.kind} · {s.source} · {s.language} · {s.status} · {fmtDate(s.created_at)}
          </p>
          <p className="record-original" lang={s.language}>
            {s.corrected_transcript_original || s.transcript_original}
          </p>
          {s.language !== "en" && s.transcript_english && <p className="record-english">{s.transcript_english}</p>}
          {s.corrections?.length > 0 && <p className="card-foot">Corrected {s.corrections.length} time(s).</p>}
          {editing?.id === s.id ? (
            <div className="inline-form">
              <textarea className="paper-input" lang={s.language} value={editing.text} onChange={(e) => setEditing({ ...editing, text: e.target.value })} />
              <input className="paper-input" placeholder="Reason for the correction" value={editing.note || ""} onChange={(e) => setEditing({ ...editing, note: e.target.value })} />
              <div className="btn-row">
                <InkButton variant="solid" onClick={save} disabled={!editing.text.trim()}>
                  Save correction
                </InkButton>
                <InkButton onClick={() => setEditing(null)}>Cancel</InkButton>
              </div>
            </div>
          ) : (
            active && (
              <InkButton onClick={() => setEditing({ id: s.id, text: s.corrected_transcript_original || s.transcript_original })}>Correct transcript</InkButton>
            )
          )}
        </article>
      ))}
    </div>
  );
}

function Interview({ sid, tick }) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    api(`/sessions/${sid}/questions`).then(setRows).catch(() => {});
  }, [sid, tick]);
  return (
    <div className="file-body">
      <h1 className="card-title ink">Interview</h1>
      {rows.length === 0 && <p>No questions asked yet.</p>}
      <ol className="qa-list">
        {rows.map((q) => (
          <li key={q.id}>
            <p className="record-meta typed">
              {q.stage} · {q.field_key}
              {q.leading_check?.used_template ? " · safe template used" : ""}
            </p>
            <p>{q.text_en}</p>
            {q.text_local && q.text_local !== q.text_en && <p className="record-original">{q.text_local}</p>}
            <p className="answer">
              <span className="typed">Answer:</span> {q.answer_type ? q.answer_option_id || q.answer_text_en || q.answer_type : "waiting"}
            </p>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Sheet({ sid, tick }) {
  const [sheet, setSheet] = useState({});
  useEffect(() => {
    api(`/sessions/${sid}/feature-sheet`)
      .then((r) => setSheet(r.sheet || {}))
      .catch(() => {});
  }, [sid, tick]);
  const rows = Object.entries(sheet);
  return (
    <div className="file-body">
      <h1 className="card-title ink">Feature sheet</h1>
      {rows.length === 0 && <p>Empty until the free-recall statement is processed.</p>}
      <table className="ledger">
        <thead>
          <tr>
            <th>Field</th>
            <th>Value</th>
            <th>Confidence</th>
            <th>Witness words</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="typed">{k}</td>
              <td>{String(v.value)}</td>
              <td>{v.confidence}</td>
              <td>{v.source_text}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Sketch({ sid, tick, user }) {
  const [tree, setTree] = useState([]);
  const [sel, setSel] = useState(null);
  const [ver, setVer] = useState(null);
  const [photo, setPhoto] = useState(false);
  useEffect(() => {
    api(`/sessions/${sid}/sketch-tree`)
      .then((t) => {
        setTree(t);
        setSel((s) => s || t[t.length - 1]?.id || null);
      })
      .catch(() => {});
  }, [sid, tick]);
  useEffect(() => {
    if (sel) api(`/sketch-versions/${sel}`).then(setVer).catch(() => {});
  }, [sel]);
  const canPhoto = ver?.master_file_id && user.role !== "admin";
  return (
    <div className="file-body">
      <h1 className="card-title ink">Sketch versions</h1>
      {tree.length === 0 && <p>No sketch yet. It appears after the witness finishes the interview.</p>}
      {ver && (
        <div className="sketch-detail">
          <div className="polaroid big-polaroid" style={{ "--rot": "-1deg" }}>
            <span className="polaroid-window square">
              <AuthImage fileId={photo && canPhoto ? ver.master_file_id : ver.sketch_file_id} />
            </span>
          </div>
          <div className="sketch-facts">
            <dl className="facts">
              <dt>Source</dt>
              <dd>{ver.edit_source}</dd>
              <dt>Edit</dt>
              <dd>{ver.edit?.type}{ver.edit?.param ? ` · ${ver.edit.param} ${ver.edit.amount ?? ""}` : ""}{ver.edit?.overlay_id ? ` · ${ver.edit.overlay_id}` : ""}</dd>
              <dt>Provider</dt>
              <dd>{ver.provider_info?.provider}</dd>
              <dt>Locked drift</dt>
              <dd>{ver.stability?.locked_drift_px ?? "-"} px</dd>
              <dt>SSIM outside</dt>
              <dd>{ver.stability?.ssim_outside_mask ?? "-"}</dd>
              <dt>Geometry</dt>
              <dd>{ver.stability?.geometry_similarity ?? "-"}</dd>
              <dt>Witness rating</dt>
              <dd>{ver.witness_rating || "-"}</dd>
            </dl>
            {ver.stability?.warning && <p className="paper-stamp small">Stability warning</p>}
            {ver.quality_warning && <p className="paper-stamp small">Quality warning</p>}
            {ver.utterance_original && <p className="record-original">“{ver.utterance_original}”</p>}
            {canPhoto && (
              <InkButton selected={photo} onClick={() => setPhoto((p) => !p)}>
                {photo ? "Show pencil sketch" : "Show photo (staff only)"}
              </InkButton>
            )}
          </div>
        </div>
      )}
      <div className="tree-row">
        {tree.map((n) => (
          <button key={n.id} type="button" className={`tree-node ${n.id === sel ? "is-selected" : ""}`} onClick={() => setSel(n.id)} title={n.id}>
            <span className="polaroid" style={{ "--rot": `${tilt(n.id, 2)}deg` }}>
              <span className="polaroid-window">
                <AuthImage fileId={n.sketch_file_id} />
              </span>
            </span>
            <span className="tree-label typed">
              {n.edit_source}
              {n.parent_id ? ` ← ${n.parent_id.slice(0, 4)}` : ""}
              {n.stability_warning ? " · !" : ""}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function Scene({ session, tick }) {
  const [tree, setTree] = useState([]);
  const [v, setV] = useState(null);
  const [sel, setSel] = useState(null);
  useEffect(() => {
    api(`/sessions/${session.id}/scene-tree`)
      .then((t) => {
        setTree(t);
        setSel((s) => s || t[t.length - 1]?.id || null);
      })
      .catch(() => {});
  }, [session.id, tick]);
  useEffect(() => {
    if (sel) api(`/scene-versions/${sel}`).then(setV).catch(() => {});
  }, [sel]);
  return (
    <div className="file-body">
      <h1 className="card-title ink">Crime scene</h1>
      {!v && <p>No scene yet. The witness builds it from the crime scene wall.</p>}
      {v && (
        <>
          <dl className="facts">
            <dt>Template</dt>
            <dd>{v.scene.template}</dd>
            <dt>Distance</dt>
            <dd>{v.analysis.distance_m ?? "-"} m</dd>
            <dt>Line of sight</dt>
            <dd>
              {v.analysis.line_of_sight}
              {v.analysis.blocking_object_id ? ` (blocked by ${v.analysis.blocking_object_id})` : ""}
            </dd>
          </dl>
          <div className="scene-frame staff-scene">
            <SceneMap scene={v.scene} showAnalysis analysis={v.analysis} labelFor={(o) => o.id} personLabel={(p) => p.role} />
          </div>
        </>
      )}
      <div className="btn-row wrap">
        {tree.map((n, i) => (
          <InkButton key={n.id} selected={n.id === sel} onClick={() => setSel(n.id)}>
            {i + 1}. {n.source}
          </InkButton>
        ))}
      </div>
    </div>
  );
}

function Exports({ sid, user }) {
  const [list, setList] = useState([]);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const canExport = user.role === "officer" || user.role === "supervisor";
  const make = async (kind) => {
    setBusy(kind);
    setError(null);
    try {
      const r = await runJob(`/sessions/${sid}/exports`, { body: { kind } });
      const url = await fileUrl(r.file_id);
      setList((l) => [{ ...r, url }, ...l]);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="file-body">
      <h1 className="card-title ink">Exports</h1>
      {!canExport && <p>Your role cannot export.</p>}
      {canExport && (
        <div className="btn-row wrap">
          {[
            ["png", "Sketch PNG"],
            ["pdf", "PDF report"],
            ["scene_png", "Scene PNG"],
            ["photoreal_png", "Photo (watermarked)"],
          ].map(([k, label]) => (
            <InkButton key={k} disabled={!!busy} onClick={() => make(k)}>
              {busy === k ? "Preparing" : label}
            </InkButton>
          ))}
        </div>
      )}
      <ErrorNote error={error} />
      <ul className="plain-list">
        {list.map((e) => (
          <li key={e.export_id} className="export-row">
            <a href={e.url} download={`nishaan-${e.kind}-${e.export_id.slice(0, 8)}.${e.kind === "pdf" ? "pdf" : "png"}`} className="ink-btn">
              <span className="ink">Download {e.kind}</span>
            </a>
            <code className="mono-id">sha256 {e.sha256}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Audit({ sid, user }) {
  const [rows, setRows] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [verify, setVerify] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(
    async (more) => {
      try {
        const r = await api(`/audit?session_id=${sid}&limit=50${more ? `&cursor=${more}` : ""}`);
        setRows((x) => (more ? [...x, ...r.items] : r.items));
        setCursor(r.next_cursor);
      } catch (e) {
        setError(e);
      }
    },
    [sid],
  );
  useEffect(() => {
    load();
  }, [load]);
  const canVerify = useMemo(() => ["supervisor", "admin"].includes(user.role), [user.role]);
  return (
    <div className="file-body">
      <h1 className="card-title ink">Audit log</h1>
      <ErrorNote error={error} />
      {canVerify && (
        <div className="btn-row">
          <InkButton
            onClick={async () => {
              try {
                setVerify(await api("/audit/verify", { method: "POST" }));
              } catch (e) {
                setError(e);
              }
            }}
          >
            Verify chain
          </InkButton>
          {verify && (verify.ok ? <span className="typed">Chain intact · {verify.checked} entries</span> : <span className="paper-stamp small">Broken at entry {verify.first_broken_id}</span>)}
        </div>
      )}
      <table className="ledger">
        <thead>
          <tr>
            <th>#</th>
            <th>When</th>
            <th>Who</th>
            <th>Action</th>
            <th>Object</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.id}</td>
              <td>{fmtDate(r.at)}</td>
              <td className="typed">{r.actor_role}</td>
              <td className="typed">{r.action}</td>
              <td className="mono-id">{r.object_type} {r.object_id ? r.object_id.slice(0, 8) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {cursor && <InkButton onClick={() => load(cursor)}>Older entries</InkButton>}
    </div>
  );
}
