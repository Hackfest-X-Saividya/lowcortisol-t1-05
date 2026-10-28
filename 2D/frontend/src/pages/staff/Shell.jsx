// Staff chrome: the evidence wall with the NISHAAN strip, a STAFF VIEW stamp, the signed-in
// officer on a torn strip, and sign-out. Redirects to sign-in when there is no session.
import { useEffect, useState } from "react";
import { Board, InkDefs } from "../../components/Board.jsx";
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

export default function Shell({ children, links = [], stamp, title }) {
  const user = auth.user;
  useEffect(() => {
    document.title = title ? `${title} · Nishaan` : "Nishaan";
  }, [title]);
  return (
    <Board className="staff" links={[["ring-tq1", "brand-pin"], ["ring-tq3", "who-pin"], ...links]}>
      <InkDefs />
      <header className="s-top">
        <a className="s-brand-link" {...linkProps(user?.role === "admin" ? "/app/admin" : "/app/cases")}>
          <Paper seed="s-brand" rotate={-1.2} jag={2.4} className="brand-strip" pins={[{ id: "brand-pin", x: "50%" }]}>
            <span className="brand ink">NISHAAN</span>
          </Paper>
        </a>
        <Stamp rotate={-1.2} className="s-stamp">
          {stamp || "Staff view"}
        </Stamp>
        {user && (
          <div className="s-who">
            <Paper seed={`who-${user.username}`} rotate={0.9} jag={2.2} className="who-strip" pins={[{ id: "who-pin", x: "50%" }]}>
              <span className="ink">
                {user.username} · {user.role}
              </span>
              <span className="who-station">{user.station || user.jurisdiction}</span>
            </Paper>
            <InkButton
              variant="wall"
              onClick={async () => {
                await auth.logout();
                navigate("/app", { replace: true });
              }}
            >
              Sign out
            </InkButton>
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
