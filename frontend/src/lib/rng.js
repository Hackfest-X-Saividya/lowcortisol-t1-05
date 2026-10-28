// Small seeded random generator so torn edges, tilts and pencil jitter are stable
// across renders (the same seed always gives the same paper).

function hash(str) {
  let h = 1779033703 ^ str.length;
  for (let i = 0; i < str.length; i++) {
    h = Math.imul(h ^ str.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  h = Math.imul(h ^ (h >>> 16), 2246822507);
  h = Math.imul(h ^ (h >>> 13), 3266489909);
  return (h ^= h >>> 16) >>> 0;
}

export function rng(seed) {
  let a = typeof seed === "number" ? seed >>> 0 : hash(String(seed));
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function between(r, lo, hi) {
  return lo + r() * (hi - lo);
}

/** A stable tilt in degrees for a seed, within +-max. */
export function tilt(seed, max = 1.5) {
  const r = rng(`tilt:${seed}`);
  return Number(((r() * 2 - 1) * max).toFixed(2));
}
