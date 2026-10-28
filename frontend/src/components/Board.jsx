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

export function Board({ children, links = [], ring = true, className = "", as: Tag = "div", ...rest }) {
  const ref = useRef(null);
  const els = useRef(new Map());
  const raf = useRef(0);
  const [pts, setPts] = useState({});
  const [size, setSize] = useState({ w: 0, h: 0 });

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

  const allLinks = ring ? [...RING_LINKS, ...links] : links;

  return (
    <BoardCtx.Provider value={api}>
      <Tag ref={ref} className={`board ${className}`} {...rest}>
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
            return <path key={`${a}-${b}`} d={d} className={opt?.thin ? "thin" : undefined} />;
          })}
        </svg>
        {ring && (
          <div className="board-ring" aria-hidden="true">
            {RING.map(([id, left, top]) => (
              <Pin key={id} id={`ring-${id}`} style={{ left, top }} />
            ))}
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
