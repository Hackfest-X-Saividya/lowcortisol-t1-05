// Staff sign-in: one index card pinned to the wall.
import { useEffect, useState } from "react";
import { Board, InkDefs } from "../../components/Board.jsx";
import { Paper, InkButton } from "../../components/Paper.jsx";
import { ArrowGlyph } from "../../components/Glyph.jsx";
import { api, auth } from "../../lib/api.js";
import { linkProps, navigate } from "../../lib/router.js";
import "../../styles/wall.css";
import "../../styles/staff.css";

const home = (u) => (u.role === "admin" ? "/app/admin" : "/app/cases");

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    document.title = "Sign in · Nishaan";
    if (auth.user) navigate(home(auth.user), { replace: true });
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const data = await api("/auth/login", { method: "POST", body: { username: username.trim(), password }, token: null });
      auth.set(data);
      navigate(home(data.user), { replace: true });
    } catch (err) {
      setError(err.code === "account_locked" ? "This account is locked for a few minutes after repeated failed attempts." : err.code === "rate_limited" ? "Too many attempts. Wait a minute and try again." : "That username and password do not match.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Board className="staff login" links={[["ring-tma", "login-pin-l"], ["ring-tmb", "login-pin-r"]]}>
      <InkDefs />
      <div className="login-wrap">
        <a className="login-brand" {...linkProps("/")}>
          <span className="brand">NISHAAN</span>
        </a>
        <form onSubmit={submit} className="login-form" aria-labelledby="login-title">
          <Paper seed="login-card" rotate={-0.7} pins={[{ id: "login-pin-l", x: "14%" }, { id: "login-pin-r", x: "86%" }]} className="login-card">
            <h1 id="login-title" className="card-title ink">
              Staff sign in
            </h1>
            <div className="field">
              <label htmlFor="u">Username</label>
              <input id="u" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="p">Password</label>
              <input id="p" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            {error && <p className="error-note">{error}</p>}
            <InkButton type="submit" variant="solid" className="ink-btn-block" disabled={busy || !username || !password} glyph={<ArrowGlyph />}>
              {busy ? "Checking" : "Sign in"}
            </InkButton>
            <p className="card-foot">
              Witnesses do not sign in here. The officer opens the witness window for them.
            </p>
          </Paper>
        </form>
      </div>
    </Board>
  );
}
