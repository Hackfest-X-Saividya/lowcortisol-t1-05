// Floor-plan walls shared by the 2D map (SceneMap) and the 3D view (CrimeScene3D).
//
// A floor plan (e.g. the sample plan, 2D/data/image.png) lists its walls: straight segments
// a -> b ([x, z] metres, x east, z south), each with its doors and windows measured from a.
// A plain room (width x depth with doors/windows on its four sides) is turned into four such
// walls, so both kinds are drawn by the same code.

const INWARD = { north: "south", south: "north", east: "west", west: "east" };
const COMPASS = { north: [0, -1], south: [0, 1], east: [1, 0], west: [-1, 0] };

export function planWalls(room) {
  if (room?.walls?.length) return room.walls;
  const W = room.width_m;
  const D = room.depth_m;
  const sides = {
    north: [[0, 0], [W, 0]],
    east: [[W, 0], [W, D]],
    south: [[0, D], [W, D]],
    west: [[0, 0], [0, D]],
  };
  return Object.entries(sides).map(([side, [a, b]]) => ({
    id: `wall_${side}`,
    a,
    b,
    exterior: true,
    openings: [
      ...(room.doors || [])
        .filter((d) => d.wall === side)
        .map((d) => ({ id: d.id, kind: "door", offset_m: d.offset_m, width_m: d.width_m, hinge: "start", opens: INWARD[side] })),
      ...(room.windows || [])
        .filter((w) => w.wall === side)
        .map((w) => ({ id: w.id, kind: "window", offset_m: w.offset_m, width_m: w.width_m })),
    ],
  }));
}

export function planOutline(room) {
  if (room?.outline?.length >= 3) return room.outline;
  const W = room.width_m;
  const D = room.depth_m;
  return [[0, 0], [W, 0], [W, D], [0, D]];
}

// Length and unit direction of a wall; (-uz, ux) is its left-hand normal.
export function wallFrame(wall) {
  const dx = wall.b[0] - wall.a[0];
  const dz = wall.b[1] - wall.a[1];
  const len = Math.hypot(dx, dz) || 1e-6;
  return { len, ux: dx / len, uz: dz / len };
}

// Openings kept on the wall and sorted along it: { ...opening, o, w, dir, side }.
// dir: +1 when the door is hinged at its edge nearer a, -1 nearer b.
// side: +1 when the leaf swings to the wall's left-hand normal, -1 to the right.
export function wallOpenings(wall) {
  const { len, ux, uz } = wallFrame(wall);
  return (wall.openings || [])
    .map((op) => {
      const o = Math.min(Math.max(Number(op.offset_m) || 0, 0), Math.max(len - 0.2, 0));
      const w = Math.min(Math.max(Number(op.width_m) || 0.9, 0.2), len - o);
      const c = COMPASS[op.opens];
      const dot = c ? -uz * c[0] + ux * c[1] : 1;
      return { ...op, o, w, dir: op.hinge === "end" ? -1 : 1, side: dot < 0 ? -1 : 1 };
    })
    .sort((p, q) => p.o - q.o);
}

// Solid runs of a wall between its openings, as [start, end] distances from a.
export function solidRuns(len, ops, extend = 0) {
  const runs = [];
  let cursor = -extend;
  ops.forEach((op) => {
    if (op.o > cursor) runs.push([cursor, op.o]);
    cursor = Math.max(cursor, op.o + op.w);
  });
  if (cursor < len + extend) runs.push([cursor, len + extend]);
  return runs;
}

// Doors and windows across all walls (for counts in messages).
export function countOpenings(room) {
  const ops = planWalls(room).flatMap((w) => w.openings || []);
  return { doors: ops.filter((o) => o.kind !== "window").length, windows: ops.filter((o) => o.kind === "window").length };
}
