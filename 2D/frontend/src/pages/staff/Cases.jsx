// Case files: every case the signed-in officer can see, as torn strips hanging one under the
// other on a string down a narrow column on the left, and a pinned sheet in the centre of the
// wall for opening a new case (officers only). Blank notes, a polaroid and pencil faces are
// pinned on the right; every pin has a string.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Pin } from "../../components/Board.jsx";
import { Paper, InkButton } from "../../components/Paper.jsx";
import { ArrowGlyph } from "../../components/Glyph.jsx";
import Torch from "../../components/Torch.jsx";
import WallDecor, { decorWiring, layoutDecor, useViewport } from "../../components/WallDecor.jsx";
import { api } from "../../lib/api.js";
import { rng, tilt } from "../../lib/rng.js";
import { linkProps, navigate } from "../../lib/router.js";
import Shell, { ErrorNote, fmtDate, useStaff } from "./Shell.jsx";

const ROLES = ["officer", "supervisor", "artist"];

// right-hand decoration: [id, kind, pin x, pin y (fractions of the screen), string to]
const DECOR = [
  ["j", "polaroid", 0.895, 0.22, "edge:right"],
  ["k", "note-index", 0.952, 0.4, "decor:j"],
  ["l", "face:round", 0.885, 0.48, "edge:right"],
  ["m", "note-scrap", 0.952, 0.66, "decor:l"],
  ["n", "face:bearded", 0.89, 0.74, "decor:m"],
];
// bottom corners only: at the top they would cut behind the case list and the officer tag
const DIAGONALS = [
  ["ring-rq3", "ring-bq3"],
  ["ring-bq1", "ring-lq3"],
];
const CHAIN_X = "28px"; // the case strips' pins sit on one line under the column's top pin

/** Strip width as a share of the column, slightly different for every case. */
function stripWidth(id) {
  return `${Math.round(86 + rng(`width:${id}`)() * 14)}%`;
}

/**
 * The string the case strips hang from: it runs from the top of the list through every strip's
 * pin. Drawn inside the scrolling list, so it scrolls with the strips; redrawn on resize.
 */
function PinChain({ children, count }) {
  const ref = useRef(null);
  const [d, setD] = useState("");
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    let frame = 0;
    const draw = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const box = el.getBoundingClientRect();
        const pts = [...el.querySelectorAll(".case-strip > .pin")].map((pin) => {
          const r = pin.getBoundingClientRect();
          return [r.left + r.width / 2 - box.left, r.top + r.height / 2 - box.top];
        });
        if (!pts.length) {
          setD("");
          return;
        }
        const all = [[pts[0][0], 0], ...pts];
        let path = `M${all[0][0].toFixed(1)} ${all[0][1].toFixed(1)}`;
        for (let i = 1; i < all.length; i++) path += ` L${all[i][0].toFixed(1)} ${all[i][1].toFixed(1)}`;
        setD(path);
      });
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(el);
    window.addEventListener("resize", draw);
    document.fonts?.ready?.then(draw);
    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      window.removeEventListener("resize", draw);
    };
  }, [count]);
  return (
    <div ref={ref} className="pin-chain">
      <svg className="pin-chain-svg" aria-hidden="true">
        {d && <path d={d} pathLength="1" />}
      </svg>
      {children}
    </div>
  );
}

export default function Cases() {
  const user = useStaff({ roles: ROLES });
  const [cases, setCases] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [error, setError] = useState(null);
  const [form, setForm] = useState({ case_number: "", crime_type: "", location_text: "", occurred_at: "" });
  const [busy, setBusy] = useState(false);
  const view = useViewport();

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
  const officer = user.role === "officer";
  const stacked = view.w <= 1100; // the top bar and the page are in one column
  const decor = view.w >= 768 ? layoutDecor(DECOR, view.w, view.h, { seed: "cases", scale: 0.92 }) : [];
  const wiring = decorWiring(decor);
  const anchors = [
    { id: "anc-files", edge: "left", follow: "files-pin" },
    ...(officer && !stacked
      ? [
          { id: "anc-new-l", edge: "top", follow: "new-pin-l" },
          { id: "anc-new-r", edge: "top", follow: "new-pin-r" },
        ]
      : []),
    ...wiring.anchors,
  ];
  const links = [
    ["anc-files", "files-pin"],
    ["files-pin", "list-top"],
    ...(officer
      ? stacked
        ? [
            ["who-pin", "new-pin-l"],
            ["signout-pin", "new-pin-r"],
          ]
        : [
            ["anc-new-l", "new-pin-l"],
            ["anc-new-r", "new-pin-r"],
          ]
      : []),
    ...wiring.links,
  ];

  return (
    <Shell
      title="Case files"
      ring="clean"
      assemble
      stacked={stacked}
      className={`cases-page ${officer ? "has-form" : ""}`}
      anchors={anchors}
      diagonals={DIAGONALS}
      links={links}
      wall={
        <>
          <WallDecor items={decor} />
          <Torch />
        </>
      }
    >
      <div className="cases-layout">
        <section className="cases-files" aria-labelledby="files-title">
          <Paper seed="files-head" rotate={-0.8} jag={2.4} className="section-strip" pins={[{ id: "files-pin", x: CHAIN_X }]}>
            <h1 id="files-title" className="ink">
              Case files
            </h1>
          </Paper>
          <ErrorNote error={error} />
          {cases.length === 0 && <p className="wall-note">No case files yet.</p>}
          <div className="cases-scroll-frame">
            <Pin id="list-top" className="list-top-pin" style={{ left: CHAIN_X }} />
            <div className="cases-scroll">
              <PinChain count={cases.length}>
                <ul className="strip-list">
                  {cases.map((c) => (
                    <li key={c.id}>
                      <a {...linkProps(`/app/cases/${c.id}`)} className="strip-link">
                        <Paper
                          seed={`case-${c.id}`}
                          rotate={tilt(c.id, 1.5)}
                          jag={2.6}
                          className="case-strip"
                          style={{ width: stripWidth(c.id) }}
                          pins={[{ x: CHAIN_X }]}
                        >
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
              </PinChain>
              {cursor && (
                <InkButton variant="wall" onClick={() => load(cursor)}>
                  Older files
                </InkButton>
              )}
            </div>
          </div>
        </section>

        {officer && (
          <section className="cases-new" aria-labelledby="new-title">
            <form onSubmit={create}>
              <Paper
                seed="new-case"
                rotate={0.6}
                pins={[
                  { id: "new-pin-l", x: "8%" },
                  { id: "new-pin-r", x: "92%" },
                ]}
                className="form-card new-case-card"
              >
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
