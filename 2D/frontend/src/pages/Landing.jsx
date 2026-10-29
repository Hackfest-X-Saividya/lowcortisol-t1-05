/*
  NISHAAN landing page.

  Layout idea: one fixed full-screen evidence wall seen head-on. The EDGES are the board:
  a ring of red string pulled taut between pins in the outer ~13-14% of the screen, with
  blank notes, polaroids and unlabeled pencil faces hanging from those pins. The CENTRE is
  calm and empty except for the wordmark, one line, and (after the intro) one Enter button.
  Every pin position is computed from the viewport, so strings always meet their pins and
  everything is recomputed on resize. A soft torch follows the mouse (not on touch).

  Tokens (styles/landing.css + styles/tokens.css):
    colour  --wall #1B2124, --manila #E4D3A8, --string #C8321E, --pin #A63A32, --ink #14120F,
            --wall-text #D8D2C4 (red is the only accent)
    type    wordmark: Special Elite (typewriter), wide tracking
            tagline: IM Fell English italic (old-printed)          // changed: tagline font
    sizes   --band-x / --band-y (13% / 14% of the screen), --torch-r 260px
*/
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { WallItem } from "../components/WallDecor.jsx";
import { navigate } from "../lib/router.js";
import { rng } from "../lib/rng.js";
import "../styles/landing.css";

const APP_ROUTE = "/app"; // placeholder route for the application

// ---- layout ------------------------------------------------------------------------------

const SIDE_DESKTOP = {
  // along: 0..1 along the side; depth: role of the pin (item / inner / outer)
  top: [
    ["1", 0.22, "item", "note-manila"],
    ["q1", 0.31, "inner"],
    ["Ma", 0.43, "item", "note-index"], // top-centre note
    ["Mb", 0.57, "item", "polaroid"], // top-centre polaroid
    ["q3", 0.69, "inner"],
    ["3", 0.78, "item", "face:bearded"],
  ],
  right: [
    ["c1", 0.24, "corner-item", "note-scrap"],
    ["q1", 0.33, "inner"],
    ["Ma", 0.43, "item", "polaroid-face:capped"], // right-middle face
    ["Mb", 0.57, "item", "note-manila"],
    ["q3", 0.67, "inner"],
    ["c3", 0.76, "corner-item", "polaroid"],
  ],
  bottom: [
    ["1", 0.22, "item", "face:narrow"],
    ["q1", 0.31, "inner"],
    ["Ma", 0.43, "item", "note-index"], // bottom-centre note
    ["Mb", 0.57, "item", "note-scrap"],
    ["q3", 0.69, "inner"],
    ["3", 0.78, "item", "polaroid-face:round"],
  ],
  left: [
    ["c1", 0.24, "corner-item", "face:moustache"], // top-left face
    ["q1", 0.33, "inner"],
    ["Ma", 0.43, "item", "polaroid-face:spectacled"], // left-middle face (polaroid)
    ["Mb", 0.57, "item", "note-manila"], // left-middle note
    ["q3", 0.67, "inner"],
    ["c3", 0.76, "corner-item", "note-scrap"],
  ],
};

const SIDE_PHONE = {
  top: [
    ["1", 0.25, "item", "note-manila"],
    ["Ma", 0.5, "item-low", "note-index"],
    ["Mb", 0.75, "item", "polaroid"],
  ],
  right: [["Ma", 0.42, "item", "face:capped"]],
  bottom: [
    ["Ma", 0.45, "item", "note-index"],
    ["Mb", 0.72, "item", "face:narrow"],
  ],
  left: [
    ["Ma", 0.36, "item", "polaroid-face:spectacled"],
    ["Mb", 0.6, "item", "note-manila"],
  ],
};

const RING_DESKTOP = [
  "TL", "T1", "Tq1", "TMa", "TMb", "Tq3", "T3",
  "TR", "Rc1", "Rq1", "RMa", "RMb", "Rq3", "Rc3",
  "BR", "B3", "Bq3", "BMb", "BMa", "Bq1", "B1",
  "BL", "Lc3", "Lq3", "LMb", "LMa", "Lq1", "Lc1", "TL",
];

// Crossings at every midpoint (bow-tie) and every corner (diagonal over the corner pin line).
const CROSS_RING_DESKTOP = [
  ["Tq1", "TMb"], ["TMa", "Tq3"],
  ["Rq1", "RMb"], ["RMa", "Rq3"],
  ["Bq1", "BMb"], ["BMa", "Bq3"],
  ["Lq1", "LMb"], ["LMa", "Lq3"],
  ["T1", "Lc1"], ["TL", "Lq1"],
  ["T3", "Rc1"], ["TR", "Rq1"],
  ["B3", "Rc3"], ["BR", "Rq3"],
  ["B1", "Lc3"], ["BL", "Lq3"],
];

const RING_PHONE = [
  ["TL", "T1"], ["T1", "TMb"], ["TMb", "TMa"], ["TMb", "TR"],
  ["TR", "RMa"], ["RMa", "BR"], ["BR", "BMb"], ["BMb", "BMa"],
  ["BMa", "BL"], ["BL", "LMb"], ["LMb", "LMa"], ["LMa", "TL"],
];

function computeLayout(W, H) {
  const phone = W < 640;
  const bandY = H * (phone ? 0.12 : 0.14);
  const bandX = W * (phone ? 0.15 : 0.13);
  const sideDepth = phone ? 0.5 : 0.3;
  const s = phone
    ? Math.max(28, Math.min(bandY * 0.52, (sideDepth * bandX - 4) / 0.46, 58))
    : Math.max(46, Math.min(bandY * 0.78 - 6, (sideDepth * bandX - 6) / 0.46, 112));
  const bottomItem = Math.min(0.96, (s + 12) / bandY);

  const pins = {};
  const add = (id, x, y) => (pins[id] = { x, y });
  const corner = (phone ? 0.3 : 0.22);
  add("TL", corner * bandX, corner * bandY);
  add("TR", W - corner * bandX, corner * bandY);
  add("BR", W - corner * bandX, H - corner * bandY);
  add("BL", corner * bandX, H - corner * bandY);

  const items = [];
  const spec = phone ? SIDE_PHONE : SIDE_DESKTOP;
  const depthOf = (side, role) => {
    const hor = side === "top" || side === "bottom";
    if (hor) {
      if (side === "top") return role === "inner" ? 0.7 : role === "item-low" ? 0.42 : 0.2;
      return role === "inner" ? 0.2 : bottomItem; // bottom: items hang from deep pins
    }
    if (role === "inner") return 0.8;
    if (role === "corner-item") return 0.55;
    return sideDepth;
  };
  const place = (side, a, d) => {
    if (side === "top") return [a * W, d * bandY];
    if (side === "bottom") return [a * W, H - d * bandY];
    if (side === "left") return [d * bandX, a * H];
    return [W - d * bandX, a * H];
  };
  const prefix = { top: "T", right: "R", bottom: "B", left: "L" };
  for (const side of Object.keys(spec)) {
    for (const [k, a, role, kind] of spec[side]) {
      const id = prefix[side] + k;
      const [x, y] = place(side, a, depthOf(side, role));
      add(id, x, y);
      if (kind) items.push({ id, pin: id, kind });
    }
  }

  // item sizes + rotation (-6..+6deg)
  const r = rng(`landing:${phone ? "p" : "d"}`);
  for (const it of items) {
    const [base, variant] = it.kind.split(":");
    it.base = base;
    it.variant = variant || null;
    const k = 0.86 + r() * 0.22;
    if (base.startsWith("polaroid")) {
      it.w = s * 0.8 * k;
      it.h = s * 0.96 * k;
    } else if (base === "face") {
      it.w = s * 0.78 * k;
      it.h = s * 0.98 * k;
    } else if (base === "note-index") {
      it.w = s * 0.92 * k;
      it.h = s * 0.62 * k;
    } else if (base === "note-scrap") {
      it.w = s * 0.7 * k;
      it.h = s * 0.66 * k;
    } else {
      it.w = s * 0.76 * k;
      it.h = s * 0.8 * k;
    }
    it.rot = Number(((r() * 2 - 1) * 6).toFixed(2));
    it.seed = `${it.id}:${phone ? "p" : "d"}`;
  }

  // ring strings
  const ring = phone
    ? RING_PHONE
    : [
        ...RING_DESKTOP.slice(0, -1).map((id, i) => [id, RING_DESKTOP[i + 1]]),
        ...CROSS_RING_DESKTOP,
      ];

  // added: cross-strings (four extra strings between pins that are not already connected)
  const P = pins;
  const sagBand = bandY;
  const cross = [];
  // a. top-left note -> top-centre note, clear downward sag (stays inside the top band)
  if (P.T1 && P.TMa) {
    const mx = (P.T1.x + P.TMa.x) / 2;
    const dip = Math.min(sagBand * 0.95, Math.max(P.T1.y, P.TMa.y) + sagBand * 0.62);
    cross.push({ id: "a", from: "T1", to: "TMa", d: `M${P.T1.x} ${P.T1.y} Q${mx} ${dip + sagBand * 0.25} ${P.TMa.x} ${P.TMa.y}` });
  }
  // b. left-middle face (polaroid) -> top-left face, nearly straight diagonal up the left side
  if (!phone && P.LMa && P.Lc1) {
    const mx = (P.LMa.x + P.Lc1.x) / 2 - 3;
    const my = (P.LMa.y + P.Lc1.y) / 2 + 4;
    cross.push({ id: "b", from: "LMa", to: "Lc1", d: `M${P.LMa.x} ${P.LMa.y} Q${mx} ${my} ${P.Lc1.x} ${P.Lc1.y}` });
  }
  // c. top-centre polaroid -> right-middle face, sweeping across the top-right corner then down
  if (!phone && P.TMb && P.RMa) {
    const c1 = [W - bandX * 0.75, bandY * 0.36];
    const c2 = [W - bandX * 0.26, H * 0.2];
    cross.push({ id: "c", from: "TMb", to: "RMa", d: `M${P.TMb.x} ${P.TMb.y} C${c1[0]} ${c1[1]} ${c2[0]} ${c2[1]} ${P.RMa.x} ${P.RMa.y}` });
  }
  // d. left-middle note -> bottom-centre note, long slightly sagging sweep across the bottom-left
  if (P.LMb && P.BMa) {
    const c1 = [bandX * (phone ? 0.45 : 0.5), H - bandY * 0.5];
    const c2 = [W * (phone ? 0.16 : 0.1), H - bandY * 0.12];
    cross.push({ id: "d", from: "LMb", to: "BMa", d: `M${P.LMb.x} ${P.LMb.y} C${c1[0]} ${c1[1]} ${c2[0]} ${c2[1]} ${P.BMa.x} ${P.BMa.y}` });
  }

  // intro timing: pins pop from the four corners inward
  const cornerDist = (pt) => Math.min(Math.hypot(pt.x, pt.y), Math.hypot(W - pt.x, pt.y), Math.hypot(W - pt.x, H - pt.y), Math.hypot(pt.x, H - pt.y));
  const maxD = Math.hypot(W, H) / 2;
  const pinDelay = {};
  for (const [id, pt] of Object.entries(pins)) pinDelay[id] = 0.35 + (cornerDist(pt) / maxD) * 0.9;

  return { phone, W, H, bandX, bandY, s, pins, items, ring, cross, pinDelay };
}

function sagPath(a, b, sag) {
  const mx = (a.x + b.x) / 2;
  const my = (a.y + b.y) / 2 + sag;
  return `M${a.x.toFixed(1)} ${a.y.toFixed(1)} Q${mx.toFixed(1)} ${my.toFixed(1)} ${b.x.toFixed(1)} ${b.y.toFixed(1)}`;
}

function samplePath(fromPt, toPt, n = 12) {
  const out = [];
  for (let i = 0; i <= n; i++) out.push([fromPt.x + ((toPt.x - fromPt.x) * i) / n, fromPt.y + ((toPt.y - fromPt.y) * i) / n]);
  return out;
}

// ---- component ---------------------------------------------------------------------------

export default function Landing() {
  const rootRef = useRef(null);
  const torchRef = useRef(null);
  const stringRefs = useRef(new Map());
  const itemRefs = useRef(new Map());
  const [size, setSize] = useState(() => ({ w: window.innerWidth, h: window.innerHeight }));
  const reduce = useMemo(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches, []);
  const touch = useMemo(() => window.matchMedia("(hover: none), (pointer: coarse)").matches, []);
  const [phase, setPhase] = useState(reduce ? "settled" : "intro"); // intro -> settled
  const [taut, setTaut] = useState(reduce);

  useLayoutEffect(() => {
    document.title = "Nishaan";
    const on = () => setSize({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  useEffect(() => {
    if (reduce) return undefined;
    const t1 = setTimeout(() => setTaut(true), 2500);
    const t2 = setTimeout(() => setPhase("settled"), 4800);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [reduce]);

  const L = useMemo(() => computeLayout(size.w, size.h), [size]);

  const strings = useMemo(() => {
    const main = L.ring
      .filter(([a, b]) => L.pins[a] && L.pins[b])
      .map(([a, b], i) => {
        const A = L.pins[a];
        const B = L.pins[b];
        const len = Math.hypot(B.x - A.x, B.y - A.y);
        return {
          key: `${a}-${b}`,
          loose: sagPath(A, B, Math.min(14, len * 0.06)),
          tight: sagPath(A, B, Math.min(2, len * 0.006)),
          samples: samplePath(A, B),
          delay: 1.3 + (i / Math.max(1, L.ring.length)) * 0.95,
        };
      });
    const cross = L.cross.map((c, i) => ({
      key: `cross-${c.id}`,
      d: c.d,
      samples: samplePath(L.pins[c.from], L.pins[c.to], 16),
      delay: 2.4 + i * 0.15, // added: cross-strings draw right after the ring, 0.15s apart
    }));
    return { main, cross };
  }, [L]);

  // torch: light circle follows the mouse; nearby strings glow, notes sway once
  const frame = useRef(0);
  const swaying = useRef(new Set());
  const onMove = useCallback(
    (e) => {
      if (touch) return;
      const { clientX: mx, clientY: my } = e;
      cancelAnimationFrame(frame.current);
      frame.current = requestAnimationFrame(() => {
        if (torchRef.current) torchRef.current.style.transform = `translate3d(${mx}px, ${my}px, 0)`;
        const R = 260;
        for (const s of [...strings.main, ...strings.cross]) {
          const el = stringRefs.current.get(s.key);
          if (!el) continue;
          let near = false;
          for (const [x, y] of s.samples) {
            if ((x - mx) ** 2 + (y - my) ** 2 < (R * 0.75) ** 2) {
              near = true;
              break;
            }
          }
          el.classList.toggle("lit", near);
        }
        if (phase !== "settled") return;
        for (const it of L.items) {
          const pin = L.pins[it.pin];
          const cx = pin.x;
          const cy = pin.y + it.h / 2;
          const el = itemRefs.current.get(it.id);
          if (!el || swaying.current.has(it.id)) continue;
          if ((cx - mx) ** 2 + (cy - my) ** 2 < 70 ** 2) {
            swaying.current.add(it.id);
            el.classList.add("sway");
          }
        }
      });
    },
    [L, strings, phase, touch],
  );

  const endSway = (id) => (e) => {
    if (e.animationName !== "landing-sway") return;
    e.currentTarget.classList.remove("sway");
    setTimeout(() => swaying.current.delete(id), 600);
  };

  const classes = ["landing", phase, reduce ? "still" : "", touch ? "touch" : "", L.phone ? "phone" : ""].join(" ");
  const pinR = L.phone ? 3.4 : 4.6;

  return (
    <div
      ref={rootRef}
      className={classes}
      onMouseMove={onMove}
      style={{ "--band-x": `${L.bandX}px`, "--band-y": `${L.bandY}px` }}
    >
      <div className="landing-wall" aria-hidden="true" />

      <svg className="landing-strings" width={L.W} height={L.H} aria-hidden="true">
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
        {/* added: cross-strings (thinner, 85% opacity, drawn behind the main ring) */}
        <g className="cross-strings">
          {strings.cross.map((s) => (
            <path
              key={s.key}
              ref={(el) => (el ? stringRefs.current.set(s.key, el) : stringRefs.current.delete(s.key))}
              className="str cross"
              d={s.d}
              pathLength="1"
              style={{ "--delay": `${s.delay}s` }}
            />
          ))}
        </g>
        <g className="main-strings">
          {strings.main.map((s) => (
            <path
              key={s.key}
              ref={(el) => (el ? stringRefs.current.set(s.key, el) : stringRefs.current.delete(s.key))}
              className="str"
              d={taut ? s.tight : s.loose}
              pathLength="1"
              style={{ "--delay": `${s.delay}s`, d: `path("${taut ? s.tight : s.loose}")` }}
            />
          ))}
        </g>
      </svg>

      <div className="landing-items" aria-hidden="true">
        {L.items.map((it, i) => {
          const pin = L.pins[it.pin];
          return (
            <div
              key={it.id}
              ref={(el) => (el ? itemRefs.current.set(it.id, el) : itemRefs.current.delete(it.id))}
              className={`board-item kind-${it.base}`}
              onAnimationEnd={endSway(it.id)}
              style={{
                left: pin.x - it.w / 2,
                top: pin.y - 3,
                width: it.w,
                height: it.h,
                "--rot": `${it.rot}deg`,
                "--delay": `${2.55 + (i / L.items.length) * 0.95}s`,
              }}
            >
              <WallItem item={it} />
            </div>
          );
        })}
      </div>

      <svg className="landing-pins" width={L.W} height={L.H} aria-hidden="true">
        {Object.entries(L.pins).map(([id, p]) => (
          <g key={id} className="pin-g" style={{ "--delay": `${L.pinDelay[id]}s` }} transform={`translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`}>
            <g className="pin-head">
              <ellipse cx="1.4" cy="2.2" rx={pinR} ry={pinR * 0.8} fill="#000" opacity=".38" />
              <circle r={pinR} fill="var(--pin)" />
              <ellipse cx={-pinR * 0.32} cy={-pinR * 0.36} rx={pinR * 0.38} ry={pinR * 0.26} fill="var(--manila)" opacity=".55" />
            </g>
          </g>
        ))}
      </svg>

      {!touch && <div ref={torchRef} className="landing-torch" aria-hidden="true" />}

      <main className="landing-centre">
        <h1 className="wordmark">NISHAAN</h1>
        <p className="tagline">Every witness holds a face.</p>
        <button
          type="button"
          className={`enter ${phase === "settled" ? "shown" : ""}`}
          onClick={() => navigate(APP_ROUTE)}
          tabIndex={phase === "settled" ? 0 : -1}
          aria-hidden={phase === "settled" ? undefined : "true"}
        >
          Enter
        </button>
      </main>
    </div>
  );
}
