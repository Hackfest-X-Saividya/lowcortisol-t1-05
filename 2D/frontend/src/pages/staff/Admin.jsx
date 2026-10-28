// User administration (admin role only): staff list on torn strips, new user card.
import { useCallback, useEffect, useState } from "react";
import { Paper, InkButton } from "../../components/Paper.jsx";
import { api } from "../../lib/api.js";
import { tilt } from "../../lib/rng.js";
import Shell, { ErrorNote, useStaff } from "./Shell.jsx";

const ROLES = ["officer", "supervisor", "artist", "admin"];

export default function Admin() {
  const user = useStaff({ roles: ["admin"] });
  const [users, setUsers] = useState([]);
  const [error, setError] = useState(null);
  const [form, setForm] = useState({ username: "", password: "", full_name: "", role: "officer", station: "", jurisdiction: "" });
  const [verify, setVerify] = useState(null);

  const load = useCallback(async () => {
    try {
      setUsers(await api("/admin/users"));
    } catch (e) {
      setError(e);
    }
  }, []);
  useEffect(() => {
    if (user) load();
  }, [user, load]);

  const patch = async (id, body) => {
    setError(null);
    try {
      await api(`/admin/users/${id}`, { method: "PATCH", body });
      load();
    } catch (e) {
      setError(e);
    }
  };

  if (!user) return null;
  return (
    <Shell title="Users" stamp="Admin view" links={[["ring-lq1", "users-pin"], ["ring-rq1", "nu-pin"]]}>
      <ErrorNote error={error} />
      <div className="s-grid two">
        <section>
          <Paper seed="users-head" rotate={-0.8} jag={2.4} className="section-strip" pins={[{ id: "users-pin", x: "20%" }]}>
            <h1 className="ink">Staff</h1>
          </Paper>
          <ul className="strip-list">
            {users.map((u) => (
              <li key={u.id}>
                <Paper seed={`u-${u.id}`} rotate={tilt(u.id, 1)} jag={2.6} className="case-strip user-strip">
                  <span className="case-no ink">{u.username}</span>
                  <span className="case-meta">
                    {u.role} · {u.station || "no station"} · {u.jurisdiction || "no jurisdiction"} · <span className="mono-id">{u.id.slice(0, 8)}</span>
                  </span>
                  <span className="btn-row">
                    <InkButton onClick={() => patch(u.id, { unlock: true })}>Unlock</InkButton>
                    <InkButton onClick={() => patch(u.id, { is_active: !u.is_active })} disabled={u.id === user.id}>
                      {u.is_active ? "Deactivate" : "Activate"}
                    </InkButton>
                    <InkButton onClick={() => navigator.clipboard?.writeText(u.id)}>Copy id</InkButton>
                  </span>
                  {!u.is_active && <span className="paper-stamp small">Inactive</span>}
                </Paper>
              </li>
            ))}
          </ul>
        </section>
        <section>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setError(null);
              try {
                await api("/admin/users", { method: "POST", body: form });
                setForm({ username: "", password: "", full_name: "", role: "officer", station: "", jurisdiction: "" });
                load();
              } catch (err) {
                setError(err);
              }
            }}
          >
            <Paper seed="new-user" rotate={0.6} pins={[{ id: "nu-pin", x: "50%" }]} className="form-card">
              <h2 className="card-title ink">New staff user</h2>
              {[
                ["username", "Username"],
                ["full_name", "Full name"],
                ["station", "Station"],
                ["jurisdiction", "Jurisdiction"],
              ].map(([k, label]) => (
                <div className="field" key={k}>
                  <label htmlFor={`nu-${k}`}>{label}</label>
                  <input id={`nu-${k}`} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} required={k === "username"} />
                </div>
              ))}
              <div className="field">
                <label htmlFor="nu-pw">Password (8+ characters)</label>
                <input id="nu-pw" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required minLength={8} />
              </div>
              <div className="field">
                <label htmlFor="nu-role">Role</label>
                <select id="nu-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                  {ROLES.map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
              </div>
              <InkButton type="submit" variant="solid">
                Create user
              </InkButton>
            </Paper>
          </form>
          <Paper seed="verify-card" rotate={-0.7} className="form-card">
            <h2 className="card-title ink">Audit chain</h2>
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
            {verify && (verify.ok ? <p className="typed">Intact · {verify.checked} entries checked</p> : <p className="paper-stamp small">Broken at entry {verify.first_broken_id}</p>)}
          </Paper>
        </section>
      </div>
    </Shell>
  );
}
