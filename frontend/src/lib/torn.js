// Torn paper edges as CSS clip-path polygons. Every edge is ragged; top and bottom differ
// because each point is drawn from the same seeded stream. Values mix % and px so the tear
// stays the same physical size whatever the paper's dimensions.
import { rng } from "./rng.js";

const f = (n) => Number(n.toFixed(2));

export function tornClip(seed, { jag = 4, side = 2, steps = 30 } = {}) {
  const r = rng(`torn:${seed}`);
  const tear = (base) => {
    const v = r() * base;
    return r() < 0.12 ? v + base * 0.9 : v; // occasional deeper bite
  };
  const pts = [];
  const vSteps = Math.max(10, Math.round(steps * 0.6));
  for (let i = 0; i <= steps; i++) pts.push(`${f((i / steps) * 100)}% ${f(tear(jag))}px`);
  for (let i = 1; i < vSteps; i++) pts.push(`calc(100% - ${f(tear(side))}px) ${f((i / vSteps) * 100)}%`);
  for (let i = steps; i >= 0; i--) pts.push(`${f((i / steps) * 100)}% calc(100% - ${f(tear(jag))}px)`);
  for (let i = vSteps - 1; i > 0; i--) pts.push(`${f(tear(side))}px ${f((i / vSteps) * 100)}%`);
  return `polygon(${pts.join(", ")})`;
}

// One or two faint fold/crease lines, as an SVG background layer.
export function creaseLayer(seed) {
  const r = rng(`crease:${seed}`);
  const lines = [];
  const n = r() < 0.35 ? 2 : 1;
  for (let i = 0; i < n; i++) {
    const vertical = r() < 0.5;
    const a = f(15 + r() * 70);
    const b = f(a + (r() - 0.5) * 12);
    lines.push(
      vertical
        ? `<line x1='${a}%' y1='0' x2='${b}%' y2='100%' stroke='%2314120F' stroke-opacity='.07' stroke-width='1'/><line x1='${a + 0.4}%' y1='0' x2='${b + 0.4}%' y2='100%' stroke='%23ffffff' stroke-opacity='.10' stroke-width='1'/>`
        : `<line x1='0' y1='${a}%' x2='100%' y2='${b}%' stroke='%2314120F' stroke-opacity='.07' stroke-width='1'/><line x1='0' y1='${a + 0.6}%' x2='100%' y2='${b + 0.6}%' stroke='%23ffffff' stroke-opacity='.10' stroke-width='1'/>`,
    );
  }
  return `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100%25' height='100%25' preserveAspectRatio='none'%3E${lines.join("").replace(/</g, "%3C").replace(/>/g, "%3E")}%3C/svg%3E")`;
}

// Torn polygon in SVG user units (used by the landing board, which draws in SVG).
export function tornPolygon(seed, w, h, { jag = 2.4, steps = 14, scrap = false } = {}) {
  const r = rng(`poly:${seed}`);
  const pts = [];
  const j = (m) => (r() - 0.2) * m;
  const sj = scrap ? jag * 2.2 : jag;
  const vs = Math.max(6, Math.round(steps * (h / Math.max(w, 1))));
  for (let i = 0; i <= steps; i++) pts.push([(i / steps) * w, Math.max(0, j(sj))]);
  for (let i = 1; i < vs; i++) pts.push([w - Math.max(0, j(scrap ? sj : jag * 0.5)), (i / vs) * h]);
  for (let i = steps; i >= 0; i--) pts.push([(i / steps) * w, h - Math.max(0, j(sj))]);
  for (let i = vs - 1; i > 0; i--) pts.push([Math.max(0, j(scrap ? sj : jag * 0.5)), (i / vs) * h]);
  if (scrap) {
    // knock a corner off so the scrap reads as torn from a bigger sheet
    const c = Math.floor(r() * 4);
    const cut = Math.min(w, h) * (0.18 + r() * 0.14);
    return pts
      .filter(([x, y]) => {
        const dx = c % 2 ? w - x : x;
        const dy = c > 1 ? h - y : y;
        return dx + dy > cut;
      })
      .map(([x, y]) => `${f(x)},${f(y)}`)
      .join(" ");
  }
  return pts.map(([x, y]) => `${f(x)},${f(y)}`).join(" ");
}
