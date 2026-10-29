// Decorative evidence pinned around the edge of a wall: blank manila notes, torn scraps, index
// cards, polaroid frames and unlabeled pencil faces, all inline SVG with no text. Shared by the
// landing page (``WallItem``) and the staff screens (``WallDecor``), where each item hangs from
// a real <Pin> so the board's strings end exactly on it.
import { useLayoutEffect, useState } from "react";
import PencilFace from "./PencilFace.jsx";
import { Pin } from "./Board.jsx";
import { rng } from "../lib/rng.js";
import { tornPolygon } from "../lib/torn.js";

/** One blank note / polaroid / face, drawn to ``item.w`` x ``item.h`` (the landing board's
 *  item renderer). Uses the ``#paper-grain`` filter from ``GrainDefs`` or the landing page. */
export function WallItem({ item }) {
  const { w, h, base, variant, seed } = item;
  const vw = 100;
  const vh = (h / w) * 100;
  const paper = (
    <polygon
      points={tornPolygon(seed, vw, vh, { scrap: base === "note-scrap", jag: base === "note-scrap" ? 2.6 : 1.8 })}
      fill="var(--manila)"
    />
  );
  let inner = null;
  if (base === "note-index") {
    const lines = [];
    for (let y = vh * 0.32; y < vh - 4; y += vh * 0.13) lines.push(<line key={y} x1="6" x2={vw - 5} y1={y} y2={y} stroke="var(--ink)" strokeOpacity=".1" strokeWidth=".7" />);
    inner = (
      <>
        <line x1="4" x2={vw - 4} y1={vh * 0.2} y2={vh * 0.2} stroke="var(--string)" strokeOpacity=".45" strokeWidth=".8" />
        {lines}
      </>
    );
  } else if (base.startsWith("polaroid")) {
    const pad = 7;
    const win = vw - pad * 2;
    inner = (
      <>
        <rect x={pad} y={pad} width={win} height={win} fill={variant ? "#d6c597" : "var(--ink)"} fillOpacity={variant ? 1 : 0.86} />
        {!variant && <ellipse cx={vw / 2} cy={pad + win * 0.45} rx={win * 0.22} ry={win * 0.27} fill="var(--wall-text)" opacity=".05" />}
        {variant && <PencilFace preset={variant} seed={seed} x={pad} y={pad} width={win} height={win} />}
      </>
    );
  } else if (base === "face") {
    inner = <PencilFace preset={variant} seed={seed} x="3" y="2" width={vw - 6} height={vh - 4} />;
  }
  return (
    <svg viewBox={`0 0 ${vw} ${vh}`} width={w} height={h} className="board-item-svg">
      <g style={{ filter: "url(#paper-grain)" }}>{paper}</g>
      {inner}
    </svg>
  );
}

/** The paper-grain filter used by ``WallItem`` (render once per page). */
export function GrainDefs() {
  return (
    <svg width="0" height="0" className="grain-defs" aria-hidden="true" focusable="false">
      <defs>
        <filter id="paper-grain" x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="4" result="n" />
          <feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -.18 .18" result="speck" />
          <feComposite in="speck" in2="SourceGraphic" operator="in" result="specks" />
          <feMerge>
            <feMergeNode in="SourceGraphic" />
            <feMergeNode in="specks" />
          </feMerge>
        </filter>
      </defs>
    </svg>
  );
}

/** The viewport size, updated on resize. */
export function useViewport() {
  const [size, setSize] = useState(() => ({ w: window.innerWidth, h: window.innerHeight }));
  useLayoutEffect(() => {
    const on = () => setSize({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return size;
}

/**
 * Lay out decorative items from specs [id, kind, fx, fy, link] (fx / fy: the pin as a fraction
 * of the viewport; link: "ring:<pin>" | "decor:<id>" | "edge:<top|right|bottom|left>").
 * Items keep a ``margin`` from the screen edges; size follows the viewport.
 */
export function layoutDecor(specs, W, H, { seed = "decor", margin = 16, scale = 1 } = {}) {
  const s = Math.max(40, Math.min(W * 0.062, H * 0.105, 96)) * scale;
  const r = rng(`${seed}:${W < 768 ? "p" : "d"}`);
  return specs.map(([id, kind, fx, fy, link]) => {
    const [base, variant] = kind.split(":");
    const k = 0.9 + r() * 0.18;
    const [fw, fh] = base.startsWith("polaroid")
      ? [0.8, 0.96]
      : base === "face"
        ? [0.78, 0.98]
        : base === "note-index"
          ? [0.92, 0.62]
          : base === "note-scrap"
            ? [0.7, 0.66]
            : [0.76, 0.8];
    const w = s * fw * k;
    const h = s * fh * k;
    const x = Math.min(Math.max(fx * W, margin + w / 2), W - margin - w / 2);
    const y = Math.min(Math.max(fy * H, margin + 6), H - margin - h);
    return { id, base, variant: variant || null, w, h, x, y, link, rot: Number(((r() * 2 - 1) * 6).toFixed(2)), seed: `${seed}:${id}` };
  });
}

/** Board links and edge anchors that hang every item from a string. */
export function decorWiring(items) {
  const links = [];
  const anchors = [];
  for (const it of items) {
    const [kind, to] = it.link.split(":");
    const pin = `decor-${it.id}`;
    if (kind === "ring") links.push([`ring-${to}`, pin]);
    else if (kind === "decor") links.push([`decor-${to}`, pin]);
    else {
      anchors.push({ id: `anc-${pin}`, edge: to, follow: pin });
      links.push([`anc-${pin}`, pin]);
    }
  }
  return { links, anchors };
}

/** The items, each hanging from its own pin (decorative: hidden from assistive tech). */
export default function WallDecor({ items, className = "" }) {
  return (
    <div className={`wall-decor ${className}`} aria-hidden="true">
      <GrainDefs />
      {items.map((it, i) => (
        <div
          key={it.id}
          className={`wall-item kind-${it.base}`}
          style={{
            left: it.x - it.w / 2,
            top: it.y - 3,
            width: it.w,
            height: it.h,
            "--rot": `${it.rot}deg`,
            "--drop": `${(0.55 + i * 0.03).toFixed(2)}s`,
          }}
        >
          <WallItem item={it} />
          <Pin id={`decor-${it.id}`} style={{ left: "50%" }} />
        </div>
      ))}
    </div>
  );
}
