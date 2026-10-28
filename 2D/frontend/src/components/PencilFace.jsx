// Pencil-style frontal face drawn in SVG (graphite lines, light hatching, no colour).
// Parameters describe the face; `highlight` circles one region in thin red (used on
// option thumbnails to show which part a question is about).
import { useId } from "react";
import { rng } from "../lib/rng.js";

const INK = "#14120F";
const RED = "#C8321E";

export const FACE_DEFAULTS = {
  shape: "oval", // oval round square long heart diamond narrow
  faceW: 1,
  faceL: 1,
  jawW: 1,
  chin: "normal", // normal round square pointed
  eyeSize: 1,
  eyeGap: 1,
  eyeShape: "almond", // almond narrow round deep_set hooded
  brow: "normal", // normal thick thin arched straight joined
  browH: 0,
  nose: "straight", // straight broad hooked small long flat upturned
  noseL: 1,
  noseW: 1,
  lips: "normal", // normal full thin
  mouthW: 1,
  hair: "short", // short short_curly medium long bald receding grey
  facial: "none", // none stubble moustache moustache_thick goatee full_beard
  head: "none", // none cap turban helmet hood
  eyewear: "none", // none spectacles sunglasses
  ears: "normal", // normal large protruding small
  cover: "none", // none mask cloth partial
  mark: "none", // none scar mole
  age: "adult", // young adult older
  shade: 0.35,
};

export const FACE_PRESETS = {
  round: { shape: "round", hair: "short" },
  narrow: { shape: "narrow", faceL: 1.06, hair: "medium", brow: "thin" },
  bearded: { facial: "full_beard", hair: "short_curly", brow: "thick" },
  capped: { head: "cap", facial: "stubble", shape: "square" },
  spectacled: { eyewear: "spectacles", hair: "receding", age: "older" },
  moustache: { facial: "moustache", shape: "square", nose: "broad", brow: "thick" },
  plain: {},
};

const fx = (n) => Number(n.toFixed(2));

// Feature group of each drawn part (used for progressive drawing during the interview).
const PART_CATEGORY = [
  ["bridgeglass", "eyewear"],
  ["shoulders", "head"],
  ["beardline", "facial"],
  ["moustache", "facial"],
  ["forehead", "age"],
  ["nostrils", "nose"],
  ["hairfill", "hair"],
  ["hairline", "hair"],
  ["sidehair", "hair"],
  ["outline", "head"],
  ["unibrow", "brows"],
  ["lipline", "mouth"],
  ["strands", "hair"],
  ["stubble", "facial"],
  ["turbanh", "headwear"],
  ["turbanl", "headwear"],
  ["helmeth", "headwear"],
  ["helmetl", "headwear"],
  ["bridge", "nose"],
  ["goatee", "facial"],
  ["coverh", "cover"],
  ["coverl", "cover"],
  ["pleats", "cover"],
  ["turban", "headwear"],
  ["helmet", "headwear"],
  ["shade", "head"],
  ["folds", "age"],
  ["upper", "mouth"],
  ["lower", "mouth"],
  ["curls", "hair"],
  ["sheen", "hair"],
  ["beard", "facial"],
  ["cover", "cover"],
  ["bands", "headwear"],
  ["neck", "head"],
  ["brow", "brows"],
  ["scar", "marks"],
  ["mole", "marks"],
  ["lens", "eyewear"],
  ["caph", "headwear"],
  ["capl", "headwear"],
  ["brim", "headwear"],
  ["hood", "headwear"],
  ["ear", "head"],
  ["eye", "eyes"],
  ["cap", "headwear"],
];
function categoryOf(key) {
  for (const [prefix, cat] of PART_CATEGORY) if (key.startsWith(prefix)) return cat;
  return "head";
}

function smooth(points, closed = false) {
  if (points.length < 2) return "";
  const p = closed
    ? [points[points.length - 1], ...points, points[0], points[1]]
    : [points[0], ...points, points[points.length - 1]];
  let d = `M${fx(points[0][0])} ${fx(points[0][1])}`;
  for (let i = 1; i < p.length - 2; i++) {
    const [p0, p1, p2, p3] = [p[i - 1], p[i], p[i + 1], p[i + 2]];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${fx(c1[0])} ${fx(c1[1])} ${fx(c2[0])} ${fx(c2[1])} ${fx(p2[0])} ${fx(p2[1])}`;
  }
  return closed ? `${d}Z` : d;
}

function mirror(points, cx) {
  return points.map(([x, y]) => [2 * cx - x, y]);
}

/** A graphite line: the main stroke plus a faint offset second pass. */
function G({ d, w = 0.75, o = 0.82, fill = "none", fo = 1, cap = "round" }) {
  return (
    <g fill={fill} fillOpacity={fo} strokeLinecap={cap} strokeLinejoin="round">
      <path d={d} stroke={INK} strokeWidth={w} strokeOpacity={o} pathLength="1" />
      <path d={d} stroke={INK} strokeWidth={w * 0.7} strokeOpacity={o * 0.35} fill="none" transform="translate(.35 .3)" pathLength="1" />
    </g>
  );
}

export default function PencilFace({ params, preset, highlight, seed = "face", className, reveal, fresh, ...svgProps }) {
  const uid = useId().replace(/[:]/g, "");
  const p = { ...FACE_DEFAULTS, ...(preset ? FACE_PRESETS[preset] : {}), ...(params || {}) };
  const r = rng(`pf:${seed}`);
  const jit = (v, a = 0.5) => v + (r() - 0.5) * a;

  // ---- head geometry -------------------------------------------------------------
  let hw = 21.5 * p.faceW;
  let L = p.faceL;
  let jaw = p.jawW;
  let chinW = 6;
  let chinDrop = 0;
  let temple = 0.95;
  switch (p.shape) {
    case "round":
      hw *= 1.1;
      L *= 0.92;
      jaw *= 1.1;
      chinW = 8.5;
      break;
    case "narrow":
      hw *= 0.86;
      L *= 1.05;
      jaw *= 0.92;
      chinW = 4.5;
      break;
    case "square":
      jaw *= 1.16;
      chinW = 10;
      break;
    case "long":
      L *= 1.14;
      hw *= 0.93;
      break;
    case "heart":
      jaw *= 0.78;
      chinW = 3;
      temple = 1.02;
      break;
    case "diamond":
      temple = 0.8;
      jaw *= 0.8;
      chinW = 3.5;
      break;
    default:
      break;
  }
  if (p.chin === "pointed") {
    chinW = 2.4;
    chinDrop = 2.2;
  }
  if (p.chin === "square") chinW = Math.max(chinW, 10);
  if (p.chin === "round") chinW = Math.max(chinW, 7.5);
  const cx = 50;
  const top = 60 - 31 * L;
  const chinY = 60 + 31 * L + chinDrop;
  const H = chinY - top;
  const at = (f) => top + f * H;

  const right = [
    [cx + hw * 0.72, at(0.07)],
    [cx + hw * temple, at(0.24)],
    [cx + hw, at(0.45)],
    [cx + hw * 0.97, at(0.62)],
    [cx + hw * jaw * 0.82, at(0.8)],
    [cx + chinW + (jaw - 1) * 4, at(0.95)],
  ];
  const outline = [[cx, top], ...right, [cx, chinY], ...mirror(right, cx).reverse()];
  const outlineD = smooth(outline.map(([x, y]) => [jit(x, 0.4), jit(y, 0.4)]), true);

  const eyeY = at(0.47);
  const eyeDx = 9.6 * p.eyeGap;
  const es = p.eyeSize;
  const browY = eyeY - 6.8 - p.browH * 3;
  const noseTip = at(0.66) + (p.noseL - 1) * 5;
  const mouthY = Math.min(at(0.81) + (p.noseL - 1) * 2, chinY - 7);
  const mw = 8.6 * p.mouthW;

  // ---- pieces --------------------------------------------------------------------
  const parts = [];

  // neck + shoulders
  const neckW = hw * 0.48;
  parts.push(
    <G key="neck" w={0.7} o={0.7} d={`M${cx - neckW} ${at(0.86)} C${cx - neckW + 1} ${chinY + 8} ${cx - neckW - 1} ${chinY + 14} ${cx - neckW - 2} ${chinY + 19} M${cx + neckW} ${at(0.86)} C${cx + neckW - 1} ${chinY + 8} ${cx + neckW + 1} ${chinY + 14} ${cx + neckW + 2} ${chinY + 19}`} />,
    <G key="shoulders" w={0.75} o={0.62} d={`M${cx - neckW - 2} ${chinY + 19} C${cx - 22} ${chinY + 22} ${cx - 38} ${chinY + 24} ${cx - 48} ${chinY + 34} M${cx + neckW + 2} ${chinY + 19} C${cx + 22} ${chinY + 22} ${cx + 38} ${chinY + 24} ${cx + 48} ${chinY + 34}`} />,
  );

  // ears
  const earS = p.ears === "large" ? 1.3 : p.ears === "small" ? 0.8 : 1;
  const earOut = p.ears === "protruding" ? 3 : 0;
  for (const s of [-1, 1]) {
    const ex = cx + s * (hw * 0.99);
    parts.push(
      <G
        key={`ear${s}`}
        w={0.7}
        o={0.75}
        d={`M${ex} ${eyeY - 2 * earS} C${ex + s * (5 + earOut) * earS} ${eyeY - 4 * earS} ${ex + s * (6 + earOut) * earS} ${eyeY + 9 * earS} ${ex + s * 0.5} ${eyeY + 11 * earS} M${ex + s * 1.4} ${eyeY + 1} C${ex + s * 3.4 * earS} ${eyeY + 1} ${ex + s * 3.2 * earS} ${eyeY + 6 * earS} ${ex + s * 1.2} ${eyeY + 7 * earS}`}
      />,
    );
  }

  // shading (hatch) on the shadow side, under cheekbone, neck
  parts.push(
    <g key="shade" opacity={p.shade}>
      <ellipse cx={cx - hw * 0.68} cy={at(0.6)} rx={hw * 0.26} ry={H * 0.15} fill={`url(#h${uid})`} />
      <path d={`M${cx - neckW} ${chinY + 2} L${cx + neckW} ${chinY + 2} L${cx + neckW} ${chinY + 12} L${cx - neckW} ${chinY + 12} Z`} fill={`url(#h${uid})`} />
      <ellipse cx={cx - 4.5} cy={noseTip - 6} rx={1.6} ry={6} fill={`url(#h${uid})`} />
    </g>,
  );

  // face outline
  parts.push(<G key="outline" w={0.95} o={0.88} d={outlineD} />);

  // age lines
  if (p.age === "older") {
    parts.push(
      <G key="forehead" w={0.45} o={0.45} d={`M${cx - 9} ${at(0.2)} Q${cx} ${at(0.18)} ${cx + 9} ${at(0.2)} M${cx - 7} ${at(0.25)} Q${cx} ${at(0.23)} ${cx + 7} ${at(0.25)}`} />,
      <G key="folds" w={0.5} o={0.5} d={`M${cx - 6} ${noseTip - 1} Q${cx - 10} ${mouthY - 3} ${cx - mw - 1} ${mouthY + 2} M${cx + 6} ${noseTip - 1} Q${cx + 10} ${mouthY - 3} ${cx + mw + 1} ${mouthY + 2}`} />,
    );
  }

  // brows
  const bw = p.brow === "thick" ? 2.1 : p.brow === "thin" ? 0.6 : 1.2;
  for (const s of [-1, 1]) {
    const x0 = cx + s * (eyeDx - 6.5);
    const x1 = cx + s * (eyeDx + 6);
    const lift = p.brow === "arched" ? -3.2 : p.brow === "straight" ? -0.3 : -1.6;
    parts.push(<G key={`brow${s}`} w={bw} o={0.85} d={`M${x0} ${browY + 0.6} Q${(x0 + x1) / 2} ${browY + lift} ${x1} ${browY + 1.4}`} />);
  }
  if (p.brow === "joined") parts.push(<G key="unibrow" w={1.2} o={0.7} d={`M${cx - 3.4} ${browY + 0.7} Q${cx} ${browY + 0.2} ${cx + 3.4} ${browY + 0.7}`} />);

  // eyes
  const eh = p.eyeShape === "narrow" ? 1.9 : p.eyeShape === "round" ? 3.9 : 2.9;
  for (const s of [-1, 1]) {
    const ex = cx + s * eyeDx;
    const w = 5.2 * es;
    const h = eh * es;
    parts.push(
      <g key={`eye${s}`}>
        <G w={0.9} o={0.9} d={`M${ex - w} ${eyeY} Q${ex} ${eyeY - h * 1.25} ${ex + w} ${eyeY}`} />
        <G w={0.55} o={0.7} d={`M${ex - w} ${eyeY} Q${ex} ${eyeY + h * 0.95} ${ex + w} ${eyeY}`} />
        <circle cx={ex} cy={eyeY - h * 0.08} r={Math.min(h * 0.62, 2.1 * es)} fill={INK} fillOpacity={0.72} />
        <circle cx={ex - 0.6} cy={eyeY - h * 0.3} r={0.45} fill="#E4D3A8" />
        {p.eyeShape === "hooded" && <G w={0.6} o={0.6} d={`M${ex - w - 0.5} ${eyeY - h * 0.55} Q${ex} ${eyeY - h * 1.05} ${ex + w + 0.5} ${eyeY - h * 0.45}`} />}
        {p.eyeShape === "deep_set" && <path d={`M${ex - w} ${eyeY - 1.5} Q${ex} ${eyeY - h * 1.9} ${ex + w} ${eyeY - 1.5} L${ex + w} ${eyeY - 3.5} Q${ex} ${eyeY - h * 2.5} ${ex - w} ${eyeY - 3.5}Z`} fill={`url(#h${uid})`} opacity={0.55} />}
        {p.age !== "young" && <G w={0.35} o={0.4} d={`M${ex - w * 0.7} ${eyeY + h * 0.9} Q${ex} ${eyeY + h * 1.4} ${ex + w * 0.7} ${eyeY + h * 0.9}`} />}
      </g>,
    );
  }

  // nose
  const nw = 4.3 * p.noseW * (p.nose === "broad" || p.nose === "flat" ? 1.35 : p.nose === "small" ? 0.8 : 1);
  const tipY = noseTip - (p.nose === "upturned" ? 1.5 : 0) - (p.nose === "small" ? 1.5 : 0) + (p.nose === "long" ? 2.5 : 0);
  const bridge =
    p.nose === "hooked"
      ? `M${cx - 1.8} ${browY + 4} C${cx - 1} ${eyeY + 4} ${cx + 2.6} ${tipY - 7} ${cx + 0.4} ${tipY - 1}`
      : `M${cx - 1.6} ${browY + 4} C${cx - 2.2} ${eyeY + 4} ${cx - 2.6} ${tipY - 6} ${cx - 2.2} ${tipY - 2}`;
  parts.push(
    <G key="bridge" w={0.6} o={0.62} d={bridge} />,
    <G key="nostrils" w={0.85} o={0.85} d={`M${cx - nw} ${tipY - 1.2} Q${cx - nw - 1.2} ${tipY + 1.6} ${cx - nw * 0.45} ${tipY + 1.4} Q${cx} ${tipY + 2.6} ${cx + nw * 0.45} ${tipY + 1.4} Q${cx + nw + 1.2} ${tipY + 1.6} ${cx + nw} ${tipY - 1.2}`} />,
  );

  // mouth
  const lipF = p.lipF ?? 1;
  const lipT = (p.lips === "full" ? 2.4 : p.lips === "thin" ? 0.7 : 1.5) * lipF;
  const lipB = (p.lips === "full" ? 3.2 : p.lips === "thin" ? 1 : 2) * lipF;
  parts.push(
    <G key="lipline" w={0.95} o={0.88} d={`M${cx - mw} ${mouthY} Q${cx - mw * 0.5} ${mouthY + 0.8} ${cx} ${mouthY + 0.2} Q${cx + mw * 0.5} ${mouthY + 0.8} ${cx + mw} ${mouthY}`} />,
    <G key="upper" w={0.5} o={0.55} d={`M${cx - mw * 0.85} ${mouthY - 0.2} Q${cx - mw * 0.35} ${mouthY - lipT} ${cx} ${mouthY - lipT * 0.6} Q${cx + mw * 0.35} ${mouthY - lipT} ${cx + mw * 0.85} ${mouthY - 0.2}`} />,
    <G key="lower" w={0.5} o={0.5} d={`M${cx - mw * 0.75} ${mouthY + 0.8} Q${cx} ${mouthY + lipB + 1.6} ${cx + mw * 0.75} ${mouthY + 0.8}`} />,
  );

  // hair
  const hairTop = top - (p.hair === "short_curly" ? 5 : 3.5);
  const hairOpacity = p.hair === "grey" ? 0.22 : 0.55;
  if (p.hair !== "bald" && p.head !== "turban" && p.head !== "helmet") {
    const hl = p.hair === "receding" ? 0.15 : 0.09;
    const cap = [
      [cx - hw * 0.99, at(0.32)],
      [cx - hw * 0.98, at(0.12)],
      [cx - hw * 0.6, hairTop + 1],
      [cx, hairTop],
      [cx + hw * 0.6, hairTop + 1],
      [cx + hw * 0.98, at(0.12)],
      [cx + hw * 0.99, at(0.32)],
      [cx + hw * 0.86, at(0.2)],
      [cx + hw * 0.45, at(hl + (p.hair === "receding" ? 0.06 : 0.03))],
      [cx, at(p.hair === "receding" ? hl + 0.04 : hl)],
      [cx - hw * 0.45, at(hl + (p.hair === "receding" ? 0.06 : 0.03))],
      [cx - hw * 0.86, at(0.2)],
    ];
    if (p.hair === "long" || p.hair === "medium") {
      const drop = p.hair === "long" ? chinY + 10 : eyeY + 8;
      cap.splice(7, 0, [cx + hw * 1.12, drop], [cx + hw * 0.98, drop - 4]);
      cap.splice(0, 0, [cx - hw * 0.98, drop - 4], [cx - hw * 1.12, drop]);
    }
    const capD = smooth(cap, true);
    parts.push(<path key="hairfill" d={capD} fill={`url(#hd${uid})`} opacity={hairOpacity + 0.25} />);
    parts.push(<G key="hairline" w={0.8} o={0.8} d={capD} />);
    // strands
    const strands = [];
    for (let i = 0; i < 9; i++) {
      const x = cx - hw * 0.8 + (i / 8) * hw * 1.6;
      strands.push(`M${fx(jit(x, 2))} ${fx(hairTop + 2)} Q${fx(x + 2)} ${fx(at(0.08))} ${fx(jit(x + 3, 2))} ${fx(at(0.12))}`);
    }
    parts.push(<G key="strands" w={0.4} o={0.5} d={strands.join(" ")} />);
    if (p.hair === "short_curly") {
      const curls = [];
      for (let i = 0; i < 14; i++) {
        const a = Math.PI * (i / 13);
        const x = cx - Math.cos(a) * hw * 0.95;
        const y = top + 4 - Math.sin(a) * 7;
        curls.push(`M${fx(x - 1.6)} ${fx(y)} a1.6 1.6 0 1 1 3.2 0`);
      }
      parts.push(<G key="curls" w={0.55} o={0.65} d={curls.join(" ")} />);
    }
  } else if (p.hair === "bald") {
    parts.push(
      <G key="sidehair" w={0.5} o={0.55} d={`M${cx - hw * 0.98} ${at(0.28)} q-1 5 0 9 M${cx - hw * 0.96} ${at(0.28)} q1 4 0 8 M${cx + hw * 0.98} ${at(0.28)} q1 5 0 9 M${cx + hw * 0.96} ${at(0.28)} q-1 4 0 8`} />,
      <G key="sheen" w={0.35} o={0.3} d={`M${cx - 6} ${top + 4} Q${cx} ${top + 2.5} ${cx + 6} ${top + 4}`} />,
    );
  }

  // facial hair
  if (p.facial === "stubble" || p.facial === "full_beard") {
    const dots = [];
    const n = p.facial === "full_beard" ? 0 : 70;
    for (let i = 0; i < n; i++) {
      const t = r();
      const side = r() < 0.5 ? -1 : 1;
      const x = cx + side * r() * (hw * 0.85 - t * 6);
      const y = mouthY - 4 + r() * (chinY - mouthY + 3);
      dots.push(<circle key={i} cx={fx(x)} cy={fx(y)} r={0.32} fill={INK} opacity={0.55} />);
    }
    parts.push(<g key="stubble">{dots}</g>);
  }
  if (p.facial === "full_beard") {
    const beard = smooth(
      [
        [cx - hw * 0.97, at(0.58)],
        [cx - hw * jaw * 0.86, at(0.82)],
        [cx - chinW - 2, chinY + 4],
        [cx, chinY + 6],
        [cx + chinW + 2, chinY + 4],
        [cx + hw * jaw * 0.86, at(0.82)],
        [cx + hw * 0.97, at(0.58)],
        [cx + hw * 0.7, at(0.72)],
        [cx + mw + 1, mouthY - 3],
        [cx, mouthY - 4.5],
        [cx - mw - 1, mouthY - 3],
        [cx - hw * 0.7, at(0.72)],
      ],
      true,
    );
    parts.push(<path key="beard" d={beard} fill={`url(#hd${uid})`} opacity={0.75} />, <G key="beardline" w={0.6} o={0.6} d={beard} />);
  }
  if (p.facial === "moustache" || p.facial === "moustache_thick" || p.facial === "full_beard") {
    const th = p.facial === "moustache_thick" ? 2.8 : 1.8;
    parts.push(
      <path
        key="moustache"
        d={`M${cx - mw - 1.5} ${mouthY - 0.5} Q${cx - mw * 0.5} ${mouthY - 4 - th} ${cx} ${mouthY - 3.2} Q${cx + mw * 0.5} ${mouthY - 4 - th} ${cx + mw + 1.5} ${mouthY - 0.5} Q${cx + mw * 0.5} ${mouthY - 2.4} ${cx} ${mouthY - 1.8} Q${cx - mw * 0.5} ${mouthY - 2.4} ${cx - mw - 1.5} ${mouthY - 0.5}Z`}
        fill={INK}
        fillOpacity={0.62}
      />,
    );
  }
  if (p.facial === "goatee") {
    parts.push(<path key="goatee" d={`M${cx - 4.5} ${mouthY + 3} Q${cx} ${mouthY + 2} ${cx + 4.5} ${mouthY + 3} L${cx + 3.5} ${chinY + 2} Q${cx} ${chinY + 4} ${cx - 3.5} ${chinY + 2}Z`} fill={`url(#hd${uid})`} opacity={0.8} />);
  }

  // marks
  if (p.mark === "scar") parts.push(<G key="scar" w={0.8} o={0.75} d={`M${cx + hw * 0.35} ${eyeY + 6} L${cx + hw * 0.6} ${eyeY + 13} M${cx + hw * 0.4} ${eyeY + 8.2} l1.6 -0.8 M${cx + hw * 0.48} ${eyeY + 10.2} l1.6 -0.8`} />);
  if (p.mark === "mole") parts.push(<circle key="mole" cx={cx + hw * 0.45} cy={eyeY + 11} r={1} fill={INK} opacity={0.8} />);

  // cover
  if (p.cover !== "none") {
    const yTop = p.cover === "partial" ? mouthY - 4 : tipY - 3;
    const d = `M${cx - hw * 0.99} ${yTop + 2} Q${cx} ${yTop - 2} ${cx + hw * 0.99} ${yTop + 2} L${cx + hw * jaw * 0.8} ${at(0.86)} Q${cx} ${chinY + 6} ${cx - hw * jaw * 0.8} ${at(0.86)}Z`;
    parts.push(<path key="cover" d={d} fill="#E4D3A8" />, <path key="coverh" d={d} fill={`url(#h${uid})`} opacity={0.35} />, <G key="coverl" w={0.8} o={0.8} d={d} />);
    if (p.cover === "mask") parts.push(<G key="pleats" w={0.4} o={0.5} d={`M${cx - hw * 0.6} ${yTop + 6} Q${cx} ${yTop + 4} ${cx + hw * 0.6} ${yTop + 6} M${cx - hw * 0.55} ${yTop + 11} Q${cx} ${yTop + 9} ${cx + hw * 0.55} ${yTop + 11}`} />);
  }

  // eyewear
  if (p.eyewear !== "none") {
    const rr = 5.6 * es + 0.6;
    const dark = p.eyewear === "sunglasses";
    for (const s of [-1, 1]) {
      const ex = cx + s * eyeDx;
      parts.push(
        <rect key={`lens${s}`} x={ex - rr} y={eyeY - rr * 0.78} width={rr * 2} height={rr * 1.56} rx={rr * 0.55} fill={dark ? INK : "none"} fillOpacity={dark ? 0.78 : 0} stroke={INK} strokeWidth={0.85} strokeOpacity={0.88} />,
      );
    }
    parts.push(<G key="bridgeglass" w={0.8} o={0.85} d={`M${cx - eyeDx + rr} ${eyeY - 1} Q${cx} ${eyeY - 3} ${cx + eyeDx - rr} ${eyeY - 1} M${cx - eyeDx - rr} ${eyeY - 1} L${cx - hw * 0.98} ${eyeY - 2} M${cx + eyeDx + rr} ${eyeY - 1} L${cx + hw * 0.98} ${eyeY - 2}`} />);
  }

  // headwear
  if (p.head === "cap") {
    const d = `M${cx - hw * 1.02} ${at(0.2)} C${cx - hw * 1.05} ${top - 9} ${cx + hw * 1.05} ${top - 9} ${cx + hw * 1.02} ${at(0.2)} Z`;
    parts.push(<path key="cap" d={d} fill="#E4D3A8" />, <path key="caph" d={d} fill={`url(#h${uid})`} opacity={0.7} />, <G key="capl" w={0.9} o={0.85} d={d} />);
    parts.push(<G key="brim" w={0.9} o={0.85} d={`M${cx - hw * 1.05} ${at(0.2)} Q${cx} ${at(0.27)} ${cx + hw * 1.05} ${at(0.2)} Q${cx} ${at(0.32)} ${cx - hw * 1.05} ${at(0.2)}`} />);
  }
  if (p.head === "turban") {
    const d = `M${cx - hw * 1.08} ${at(0.24)} C${cx - hw * 1.25} ${top - 14} ${cx + hw * 1.25} ${top - 14} ${cx + hw * 1.08} ${at(0.24)} Q${cx} ${at(0.12)} ${cx - hw * 1.08} ${at(0.24)}Z`;
    parts.push(<path key="turban" d={d} fill="#E4D3A8" />, <path key="turbanh" d={d} fill={`url(#h${uid})`} opacity={0.45} />, <G key="turbanl" w={0.9} o={0.85} d={d} />);
    parts.push(<G key="bands" w={0.5} o={0.55} d={`M${cx - hw} ${at(0.17)} Q${cx} ${top - 6} ${cx + hw} ${at(0.04)} M${cx - hw * 0.9} ${at(0.05)} Q${cx} ${top - 8} ${cx + hw} ${at(0.17)}`} />);
  }
  if (p.head === "helmet") {
    const d = `M${cx - hw * 1.14} ${at(0.5)} C${cx - hw * 1.3} ${top - 16} ${cx + hw * 1.3} ${top - 16} ${cx + hw * 1.14} ${at(0.5)} L${cx + hw * 0.98} ${at(0.5)} C${cx + hw * 1.02} ${at(0.22)} ${cx - hw * 1.02} ${at(0.22)} ${cx - hw * 0.98} ${at(0.5)}Z`;
    parts.push(<path key="helmet" d={d} fill="#E4D3A8" />, <path key="helmeth" d={d} fill={`url(#hd${uid})`} opacity={0.6} />, <G key="helmetl" w={1} o={0.88} d={d} />);
  }
  if (p.head === "hood") {
    parts.push(<G key="hood" w={1} o={0.8} d={`M${cx - hw * 0.8} ${chinY + 18} C${cx - hw * 1.5} ${at(0.6)} ${cx - hw * 1.4} ${top - 12} ${cx} ${top - 12} C${cx + hw * 1.4} ${top - 12} ${cx + hw * 1.5} ${at(0.6)} ${cx + hw * 0.8} ${chinY + 18}`} />);
  }

  // highlight ring for thumbnails
  const hl = {
    eyes: [cx, eyeY, hw * 0.88, 6.5],
    brows: [cx, browY, hw * 0.86, 4.5],
    nose: [cx, tipY - 5, 7, 10],
    mouth: [cx, mouthY, mw + 3.5, 5.5],
    lips: [cx, mouthY, mw + 3.5, 5.5],
    jaw: [cx, at(0.88), hw * 1.02, 9],
    face_shape: [cx, (top + chinY) / 2, hw * 1.12, H * 0.58],
    hair: [cx, top + 2, hw * 1.08, 9],
    head: [cx, top + 2, hw * 1.08, 9],
    ears: null,
    skin: [cx - hw * 0.5, at(0.62), 7, 7],
    marks: [cx + hw * 0.5, eyeY + 10, 6.5, 6.5],
    facial_hair: [cx, mouthY + 3, hw * 0.75, 8],
  }[highlight];

  return (
    <svg viewBox="0 0 100 120" className={className} role="img" aria-hidden="true" {...svgProps}>
      <defs>
        <pattern id={`h${uid}`} width="2.6" height="2.6" patternUnits="userSpaceOnUse" patternTransform="rotate(38)">
          <line x1="0" y1="0" x2="0" y2="2.6" stroke={INK} strokeWidth="0.5" strokeOpacity="0.55" />
        </pattern>
        <pattern id={`hd${uid}`} width="1.6" height="1.6" patternUnits="userSpaceOnUse" patternTransform="rotate(-30)">
          <line x1="0" y1="0" x2="0" y2="1.6" stroke={INK} strokeWidth="0.55" strokeOpacity="0.75" />
        </pattern>
      </defs>
      {parts.map((el) => {
        const cat = categoryOf(String(el.key));
        if (!reveal) return el;
        const on = reveal.includes(cat);
        return (
          <g key={el.key} opacity={on ? 1 : 0.13} className={on && fresh?.includes(cat) ? "pf-draw" : undefined}>
            {el}
          </g>
        );
      })}
      {hl && <ellipse cx={hl[0]} cy={hl[1]} rx={hl[2]} ry={hl[3]} fill="none" stroke={RED} strokeWidth="1.3" />}
      {highlight === "ears" &&
        [-1, 1].map((s) => <ellipse key={s} cx={cx + s * (hw + 3)} cy={eyeY + 4} rx={5} ry={9} fill="none" stroke={RED} strokeWidth="1.3" />)}
    </svg>
  );
}
