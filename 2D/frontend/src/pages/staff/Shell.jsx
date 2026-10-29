// Staff chrome: the evidence wall with the NISHAAN strip, a STAFF VIEW stamp, the signed-in
// officer on a torn strip, and sign-out. Redirects to sign-in when there is no session.
import { useEffect, useState } from "react";
import { Board, InkDefs, Pin } from "../../components/Board.jsx";
import { Paper, Stamp, InkButton } from "../../components/Paper.jsx";
import { auth } from "../../lib/api.js";
import { linkProps, navigate } from "../../lib/router.js";
import "../../styles/wall.css";
import "../../styles/staff.css";

export function useStaff({ roles } = {}) {
  const [user, setUser] = useState(auth.user);
  useEffect(() => auth.subscribe(setUser), []);
  useEffect(() => {
    if (!user) navigate("/app", { replace: true });
    else if (roles && !roles.includes(user.role)) navigate(user.role === "admin" ? "/app/admin" : "/app/cases", { replace: true });
  }, [user, roles]);
  return user;
}

// Clean wall (ring="clean"): every top-bar item hangs from a string that runs straight up to
// the ring, including the stamp and the sign-out button.
const TOP_ANCHORS = [
  { id: "anc-brand", edge: "top", follow: "brand-pin" },
  { id: "anc-stamp", edge: "top", follow: "stamp-pin" },
  { id: "anc-who", edge: "top", follow: "who-pin" },
  { id: "anc-signout", edge: "top", follow: "signout-pin" },
];

export default function Shell({ children, links = [], stamp, title, ring, anchors = [], diagonals = [], assemble = false, stacked = false, className = "", wall = null }) {
  const user = auth.user;
  const clean = ring === "clean";
  useEffect(() => {
    document.title = title ? `${title} · Nishaan` : "Nishaan";
  }, [title]);
  // stacked (narrow screens, the top bar in one column): the items hang from one another
  // instead of each running a long string up past the ones above it
  const topLinks = stacked
    ? [["anc-brand", "brand-pin"], ["brand-pin", "stamp-pin"], ["stamp-pin", "who-pin"], ["who-pin", "signout-pin"]]
    : [["anc-brand", "brand-pin"], ["anc-stamp", "stamp-pin"], ["anc-who", "who-pin"], ["anc-signout", "signout-pin"]];
  const boardProps = clean
    ? {
        ring: "clean",
        assemble,
        diagonals,
        anchors: [...(stacked ? TOP_ANCHORS.slice(0, 1) : TOP_ANCHORS), ...anchors],
        links: [...topLinks, ...links],
      }
    : { links: [["ring-tq1", "brand-pin"], ["ring-tq3", "who-pin"], ...links] };
  const stampEl = (
    <Stamp rotate={-1.2} className="s-stamp">
      {stamp || "Staff view"}
    </Stamp>
  );
  const signOut = (
    <InkButton
      variant="wall"
      onClick={async () => {
        await auth.logout();
        navigate("/app", { replace: true });
      }}
    >
      Sign out
    </InkButton>
  );
  return (
    <Board className={`staff ${className}`} {...boardProps}>
      <InkDefs />
      {wall}
      <header className="s-top">
        <a className="s-brand-link" {...linkProps(user?.role === "admin" ? "/app/admin" : "/app/cases")}>
          <Paper seed="s-brand" rotate={-1.2} jag={2.4} className="brand-strip" pins={[{ id: "brand-pin", x: "50%" }]}>
            <span className="brand ink">NISHAAN</span>
          </Paper>
        </a>
        {clean ? (
          <span className="s-stamp-wrap">
            {stampEl}
            <Pin id="stamp-pin" style={{ left: "50%" }} />
          </span>
        ) : (
          stampEl
        )}
        {user && (
          <div className="s-who">
            <Paper seed={`who-${user.username}`} rotate={0.9} jag={2.2} className="who-strip" pins={[{ id: "who-pin", x: "50%" }]}>
              <span className="ink">
                {user.username} · {user.role}
              </span>
              <span className="who-station">{user.station || user.jurisdiction}</span>
            </Paper>
            {clean ? (
              <span className="s-signout">
                {signOut}
                <Pin id="signout-pin" style={{ left: "50%" }} />
              </span>
            ) : (
              signOut
            )}
          </div>
        )}
      </header>
      <main className="s-main">{children}</main>
    </Board>
  );
}

export function ErrorNote({ error }) {
  if (!error) return null;
  return <p className="error-note">{error.message || String(error)}</p>;
}

export function fmtDate(v) {
  if (!v) return "";
  const d = new Date(v);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
