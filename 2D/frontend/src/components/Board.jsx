// The evidence wall for application screens.
//
// <Board> draws the wall (felt, faint lamp glow from the top-left), a ring of red string in
// the outer margin, and any extra `links` between named pins. Pins are real DOM elements
// (<Pin id="...">) placed on paper; the board measures their centres and draws every string
// so that it starts and ends exactly on a pin, re-measuring on resize and layout changes.
// Strings sit behind all content.
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

const BoardCtx = createContext(null);

const RING = [
  // id, css position (left, top) – corners and mid-sides on the outer margin, quarter
  // pins slightly deeper so the ring zigzags and crosses itself at the midpoints.
  ["tl", "var(--ring-i)", "var(--ring-i)"],
  ["tq1", "25%", "var(--ring-d)"],
  ["tma", "45%", "var(--ring-i)"],
  ["tmb", "55%", "var(--ring-i)"],
  ["tq3", "75%", "var(--ring-d)"],
  ["tr", "calc(100% - var(--ring-i))", "var(--ring-i)"],
  ["rq1", "calc(100% - var(--ring-d))", "25%"],
  ["rma", "calc(100% - var(--ring-i))", "45%"],
  ["rmb", "calc(100% - var(--ring-i))", "55%"],
  ["rq3", "calc(100% - var(--ring-d))", "75%"],
  ["br", "calc(100% - var(--ring-i))", "calc(100% - var(--ring-i))"],
  ["bq3", "75%", "calc(100% - var(--ring-d))"],
  ["bmb", "55%", "calc(100% - var(--ring-i))"],
  ["bma", "45%", "calc(100% - var(--ring-i))"],
  ["bq1", "25%", "calc(100% - var(--ring-d))"],
  ["bl", "var(--ring-i)", "calc(100% - var(--ring-i))"],
  ["lq3", "var(--ring-d)", "75%"],
  ["lmb", "var(--ring-i)", "55%"],
  ["lma", "var(--ring-i)", "45%"],
  ["lq1", "var(--ring-d)", "25%"],
];

const RING_LINKS = [
  ...RING.map(([id], i) => [`ring-${id}`, `ring-${RING[(i + 1) % RING.length][0]}`]),
  // crossings at every midpoint
  ["ring-tq1", "ring-tmb"],
  ["ring-tma", "ring-tq3"],
  ["ring-rq1", "ring-rmb"],
  ["ring-rma", "ring-rq3"],
  ["ring-bq1", "ring-bmb"],
  ["ring-bma", "ring-bq3"],
  ["ring-lq1", "ring-lmb"],
  ["ring-lma", "ring-lq3"],
];

// The clean ring (ring="clean"): pins at the corners, the quarter points and the middle of each
// side, one string per edge segment (pins on an edge are joined in order, so extra anchors slot
// in), plus the diagonals a page asks for. [id, left, top, edges]
const CLEAN = [
  ["tl", "var(--ring-i)", "var(--ring-i)", ["top", "left"]],
  ["tq1", "25%", "var(--ring-i)", ["top"]],
  ["tm", "50%", "var(--ring-i)", ["top"]],
  ["tq3", "75%", "var(--ring-i)", ["top"]],
  ["tr", "calc(100% - var(--ring-i))", "var(--ring-i)", ["top", "right"]],
  ["rq1", "calc(100% - var(--ring-i))", "25%", ["right"]],
  ["rm", "calc(100% - var(--ring-i))", "50%", ["right"]],
  ["rq3", "calc(100% - var(--ring-i))", "75%", ["right"]],
  ["br", "calc(100% - var(--ring-i))", "calc(100% - var(--ring-i))", ["bottom", "right"]],
  ["bq3", "75%", "calc(100% - var(--ring-i))", ["bottom"]],
  ["bm", "50%", "calc(100% - var(--ring-i))", ["bottom"]],
  ["bq1", "25%", "calc(100% - var(--ring-i))", ["bottom"]],
  ["bl", "var(--ring-i)", "calc(100% - var(--ring-i))", ["bottom", "left"]],
  ["lq3", "var(--ring-i)", "75%", ["left"]],
  ["lm", "var(--ring-i)", "50%", ["left"]],
  ["lq1", "var(--ring-i)", "25%", ["left"]],
];

/** Position of an anchor pin on the ring edge, level with the pin it follows. */
function anchorStyle(edge, p) {
  if (edge === "top") return { left: `${p.x}px`, top: "var(--ring-i)" };
  if (edge === "bottom") return { left: `${p.x}px`, top: "calc(100% - var(--ring-i))" };
  if (edge === "left") return { left: "var(--ring-i)", top: `${p.y}px` };
  return { left: "calc(100% - var(--ring-i))", top: `${p.y}px` };
}

const FRACTION = { tq1: 0.25, tm: 0.5, tq3: 0.75, bq1: 0.25, bm: 0.5, bq3: 0.75, lq1: 0.25, lm: 0.5, lq3: 0.75, rq1: 0.25, rm: 0.5, rq3: 0.75 };

/** Ring pins left out because an anchor sits on top of them (one pin, not two in one spot). */
function crowded(pts, anchors, w, h) {
  const out = new Set();
  for (const [id, , , edges] of CLEAN) {
    const f = FRACTION[id];
    if (f === undefined) continue; // corners always stay
    const edge = edges[0];
    const horizontal = edge === "top" || edge === "bottom";
    const at = f * (horizontal ? w : h);
    for (const a of anchors) {
      const p = pts[a.follow];
      if (a.edge === edge && p && Math.abs((horizontal ? p.x : p.y) - at) < 16) out.add(id);
    }
  }
  return out;
}

/** One string between each pair of neighbouring pins along every edge of the clean ring. */
function edgeLinks(pts, anchors, skip) {
  const out = [];
  for (const edge of ["top", "right", "bottom", "left"]) {
    const ids = [
      ...CLEAN.filter(([id, , , edges]) => edges.includes(edge) && !skip.has(id)).map(([id]) => `ring-${id}`),
      ...anchors.filter((a) => a.edge === edge).map((a) => a.id),
    ].filter((id) => pts[id]);
    const key = edge === "top" || edge === "bottom" ? "x" : "y";
    ids.sort((a, b) => pts[a][key] - pts[b][key]);
    for (let i = 1; i < ids.length; i++) out.push([ids[i - 1], ids[i]]);
  }
  return out;
}

/** Seconds after the start of the assemble animation, growing from the corners inwards. */
function fromCorner(x, y, w, h) {
  const d = Math.min(Math.hypot(x, y), Math.hypot(w - x, y), Math.hypot(w - x, h - y), Math.hypot(x, h - y));
  return d / Math.max(1, Math.hypot(w, h) / 2);
}

const ASSEMBLE_MS = 1500;

function same(a, b) {
  const ka = Object.keys(a);
  if (ka.length !== Object.keys(b).length) return false;
  for (const k of ka) {
    const p = a[k];
    const q = b[k];
    if (!q || Math.abs(p.x - q.x) > 0.5 || Math.abs(p.y - q.y) > 0.5) return false;
  }
  return true;
}

/**
 * ring: true (the zigzag ring), false, or "clean" (see CLEAN).
 * anchors (clean ring only): [{ id, edge, follow }] extra ring pins placed on an edge level with
 *   the pin ``follow``, so the string to that pin runs straight to the edge.
 * diagonals (clean ring only): [[ringPinId, ringPinId]] corner strings.
 * assemble: play the assemble animation once on mount (pins pop in from the corners, strings
 *   draw, paper drops and settles); skipped under prefers-reduced-motion.
 */
export function Board({ children, links = [], ring = true, anchors = [], diagonals = [], assemble = false, className = "", as: Tag = "div", ...rest }) {
  const ref = useRef(null);
  const els = useRef(new Map());
  const raf = useRef(0);
  const [pts, setPts] = useState({});
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [assembling, setAssembling] = useState(
    () => assemble && !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );
  const assemblingRef = useRef(assembling);
  assemblingRef.current = assembling;

  // plays once on mount only: re-renders, typing and state changes never restart it
  useEffect(() => {
    if (!assemblingRef.current) return undefined;
    const t = setTimeout(() => setAssembling(false), ASSEMBLE_MS);
    return () => clearTimeout(t);
  }, []);

  const measure = useCallback(() => {
    cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(() => {
      const b = ref.current;
      if (!b) return;
      const br = b.getBoundingClientRect();
      const next = {};
      els.current.forEach((el, id) => {
        if (!el.isConnected) return;
        const r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) return;
        next[id] = { x: r.left + r.width / 2 - br.left, y: r.top + r.height / 2 - br.top };
        if (assemblingRef.current && !el.style.getPropertyValue("--pop")) {
          const p = next[id];
          el.style.setProperty("--pop", `${(fromCorner(p.x, p.y, br.width, br.height) * 0.3).toFixed(3)}s`);
        }
      });
      setSize((s) => (s.w === b.scrollWidth && s.h === b.scrollHeight ? s : { w: b.scrollWidth, h: b.scrollHeight }));
      setPts((prev) => (same(prev, next) ? prev : next));
    });
  }, []);

  const api = useMemo(
    () => ({
      register(id, el) {
        els.current.set(id, el);
        measure();
      },
      unregister(id, el) {
        if (els.current.get(id) === el) els.current.delete(id);
        measure();
      },
      measure,
    }),
    [measure],
  );

  useEffect(() => {
    const b = ref.current;
    const ro = new ResizeObserver(measure);
    ro.observe(b);
    const mo = new MutationObserver((list) => {
      if (list.some((m) => !(m.target instanceof SVGElement && m.target.closest?.(".board-strings")))) measure();
    });
    mo.observe(b, { subtree: true, childList: true, attributes: true, attributeFilter: ["class"] });
    window.addEventListener("resize", measure);
    window.addEventListener("load", measure);
    document.fonts?.ready?.then(measure);
    // late image loads change layout without DOM mutations
    const onLoad = (e) => e.target instanceof HTMLImageElement && measure();
    b.addEventListener("load", onLoad, true);
    return () => {
      ro.disconnect();
      mo.disconnect();
      b.removeEventListener("load", onLoad, true);
      window.removeEventListener("resize", measure);
      window.removeEventListener("load", measure);
    };
  }, [measure]);

  const clean = ring === "clean";
  const skip = clean ? crowded(pts, anchors, size.w, size.h) : new Set();
  const allLinks = clean ? [...edgeLinks(pts, anchors, skip), ...diagonals, ...links] : ring ? [...RING_LINKS, ...links] : links;

  // anchors move with the pins they follow: measure again once they are placed
  const anchorKey = clean ? anchors.map((a) => `${a.id}:${pts[a.follow]?.x?.toFixed(0)}:${pts[a.follow]?.y?.toFixed(0)}`).join("|") : "";
  useLayoutEffect(() => {
    if (anchorKey) measure();
  }, [anchorKey, measure]);

  return (
    <BoardCtx.Provider value={api}>
      <Tag ref={ref} className={`board ${assembling ? "assemble" : ""} ${className}`} {...rest}>
        <div className="board-wall" aria-hidden="true" />
        <svg className="board-strings" aria-hidden="true" data-w={size.w} data-h={size.h}>
          {allLinks.map((l) => {
            const [a, b, opt] = Array.isArray(l) ? l : [l.from, l.to, l];
            const A = pts[a];
            const B = pts[b];
            if (!A || !B) return null;
            const len = Math.hypot(B.x - A.x, B.y - A.y);
            const sag = opt?.sag ?? Math.min(9, len * 0.025);
            const d = `M${A.x.toFixed(1)} ${A.y.toFixed(1)} Q${((A.x + B.x) / 2).toFixed(1)} ${((A.y + B.y) / 2 + sag).toFixed(1)} ${B.x.toFixed(1)} ${B.y.toFixed(1)}`;
            const draw = assembling ? { "--draw": `${(0.22 + fromCorner((A.x + B.x) / 2, (A.y + B.y) / 2, size.w, size.h) * 0.42).toFixed(3)}s` } : undefined;
            return <path key={`${a}-${b}`} d={d} pathLength="1" style={draw} className={opt?.thin ? "thin" : undefined} />;
          })}
        </svg>
        {ring && (
          <div className="board-ring" aria-hidden="true">
            {(clean ? CLEAN.filter(([id]) => !skip.has(id)) : RING).map(([id, left, top]) => (
              <Pin key={id} id={`ring-${id}`} style={{ left, top }} />
            ))}
            {clean &&
              anchors.map((a) => (pts[a.follow] ? <Pin key={a.id} id={a.id} style={anchorStyle(a.edge, pts[a.follow])} /> : null))}
          </div>
        )}
        {children}
      </Tag>
    </BoardCtx.Provider>
  );
}

export function useBoard() {
  return useContext(BoardCtx);
}

/** A glossy pin head. Registers itself so strings can end exactly on it. */
export function Pin({ id, tone = "red", className = "", style }) {
  const board = useContext(BoardCtx);
  const ref = useRef(null);
  useLayoutEffect(() => {
    if (!board || !id) return undefined;
    const el = ref.current;
    board.register(id, el);
    return () => board.unregister(id, el);
  }, [board, id]);
  return <span ref={ref} aria-hidden="true" className={`pin pin-${tone} ${className}`} style={style} />;
}

/** Kept for compatibility: the ink effect is now pure CSS (no SVG filter). */
export function InkDefs() {
  return null;
}
