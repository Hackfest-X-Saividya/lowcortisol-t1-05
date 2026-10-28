// Case files: every case the signed-in officer can see, as torn strips, plus a pinned card
// for opening a new case (officers only).
import { useCallback, useEffect, useState } from "react";
import { Paper, InkButton } from "../../components/Paper.jsx";
import { ArrowGlyph } from "../../components/Glyph.jsx";
import { api } from "../../lib/api.js";
import { tilt } from "../../lib/rng.js";
import { linkProps, navigate } from "../../lib/router.js";
import Shell, { ErrorNote, fmtDate, useStaff } from "./Shell.jsx";

const ROLES = ["officer", "supervisor", "artist"];

export default function Cases() {
  const user = useStaff({ roles: ROLES });
  const [cases, setCases] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [error, setError] = useState(null);
  const [form, setForm] = useState({ case_number: "", crime_type: "", location_text: "", occurred_at: "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (more) => {
    try {
      const q = more ? `?cursor=${encodeURIComponent(more)}` : "";
      const page = await api(`/cases${q}`);
      setCases((c) => (more ? [...c, ...page.items] : page.items));
      setCursor(page.next_cursor);
    } catch (e) {
      setError(e);
    }
  }, []);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  const create = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = { case_number: form.case_number.trim(), crime_type: form.crime_type.trim(), location_text: form.location_text.trim() };
      if (form.occurred_at) body.occurred_at = new Date(form.occurred_at).toISOString();
      const c = await api("/cases", { method: "POST", body });
      navigate(`/app/cases/${c.id}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  if (!user) return null;
  const links = [["ring-lq1", "files-pin"], ...(user.role === "officer" ? [["ring-rq1", "new-pin"]] : [])];

  return (
    <Shell title="Case files" links={links}>
      <div className="s-grid two">
        <section aria-labelledby="files-title">
          <Paper seed="files-head" rotate={-0.8} jag={2.4} className="section-strip" pins={[{ id: "files-pin", x: "20%" }]}>
            <h1 id="files-title" className="ink">
              Case files
            </h1>
          </Paper>
          <ErrorNote error={error} />
          {cases.length === 0 && <p className="wall-note">No case files yet.</p>}
          <ul className="strip-list">
            {cases.map((c) => (
              <li key={c.id}>
                <a {...linkProps(`/app/cases/${c.id}`)} className="strip-link">
                  <Paper seed={`case-${c.id}`} rotate={tilt(c.id, 1.2)} jag={2.6} className="case-strip">
                    <span className="case-no ink">{c.case_number}</span>
                    <span className="case-meta">
                      {c.crime_type || "unspecified"} · {c.station} · {fmtDate(c.created_at)}
                    </span>
                    {c.status !== "open" && <span className="paper-stamp small">{c.status}</span>}
                  </Paper>
                </a>
              </li>
            ))}
          </ul>
          {cursor && (
            <InkButton variant="wall" onClick={() => load(cursor)}>
              Older files
            </InkButton>
          )}
        </section>

        {user.role === "officer" && (
          <section aria-labelledby="new-title">
            <form onSubmit={create}>
              <Paper seed="new-case" rotate={0.6} pins={[{ id: "new-pin", x: "50%" }]} className="form-card">
                <h2 id="new-title" className="card-title ink">
                  Open a new case
                </h2>
                <div className="field">
                  <label htmlFor="cn">Case number</label>
                  <input id="cn" value={form.case_number} onChange={(e) => setForm({ ...form, case_number: e.target.value })} required />
                </div>
                <div className="field">
                  <label htmlFor="ct">Crime type</label>
                  <input id="ct" value={form.crime_type} onChange={(e) => setForm({ ...form, crime_type: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="cl">Location</label>
                  <input id="cl" value={form.location_text} onChange={(e) => setForm({ ...form, location_text: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="co">Occurred at</label>
                  <input id="co" type="datetime-local" value={form.occurred_at} onChange={(e) => setForm({ ...form, occurred_at: e.target.value })} />
                </div>
                <p className="card-foot">Station: {user.station}</p>
                <InkButton type="submit" variant="solid" disabled={busy || !form.case_number.trim()} glyph={<ArrowGlyph />}>
                  Open case
                </InkButton>
              </Paper>
            </form>
          </section>
        )}
      </div>
    </Shell>
  );
}
