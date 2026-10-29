// Staff sign-in: one index card pinned to the wall, hanging from two pins on strings that run
// straight up to the ring, with blank notes, polaroids and pencil faces pinned in the corners.
import { useEffect, useState } from "react";
import { Board, InkDefs } from "../../components/Board.jsx";
import Torch from "../../components/Torch.jsx";
import WallDecor, { decorWiring, layoutDecor, useViewport } from "../../components/WallDecor.jsx";
import { Paper, InkButton } from "../../components/Paper.jsx";
import { ArrowGlyph } from "../../components/Glyph.jsx";
import { api, auth } from "../../lib/api.js";
import { linkProps, navigate } from "../../lib/router.js";
import "../../styles/wall.css";
import "../../styles/staff.css";

const home = (u) => (u.role === "admin" ? "/app/admin" : "/app/cases");

// [id, kind, pin x, pin y (fractions of the screen), what its string goes to, shown on phones]
// Corners only: nothing enters the middle 40% of the width or the middle 55% of the height.
const DECOR = [
  ["a", "face:round", 0.19, 0.12, "ring:tl", true],
  ["b", "note-manila", 0.065, 0.11, "decor:a", false],
  ["c", "polaroid", 0.81, 0.12, "ring:tr", true],
  ["d", "note-index", 0.935, 0.11, "decor:c", false],
  ["i", "face:capped", 0.735, 0.06, "decor:d", false],
  ["e", "face:bearded", 0.81, 0.79, "ring:br", true],
  ["f", "note-scrap", 0.93, 0.845, "decor:e", false],
  ["g", "face:narrow", 0.19, 0.79, "ring:bl", true],
  ["h", "polaroid", 0.07, 0.845, "decor:g", false],
];
const DIAGONALS = [
  ["ring-tq1", "ring-lq1"],
  ["ring-tq3", "ring-rq1"],
  ["ring-rq3", "ring-bq3"],
  ["ring-bq1", "ring-lq3"],
];
const CARD_ANCHORS = [
  { id: "anc-login-l", edge: "top", follow: "login-pin-l" },
  { id: "anc-login-r", edge: "top", follow: "login-pin-r" },
];

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const view = useViewport();
  const phone = view.w < 768;
  const decor = layoutDecor(
    DECOR.filter((d) => !phone || d[5]),
    view.w,
    view.h,
    { seed: "login" },
  );
  const wiring = decorWiring(decor);

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
    <Board
      className="staff login"
      ring="clean"
      assemble
      anchors={[...CARD_ANCHORS, ...wiring.anchors]}
      diagonals={DIAGONALS}
      links={[["anc-login-l", "login-pin-l"], ["anc-login-r", "login-pin-r"], ...wiring.links]}
    >
      <InkDefs />
      <WallDecor items={decor} />
      <Torch />
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
