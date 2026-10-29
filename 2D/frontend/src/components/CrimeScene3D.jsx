// CrimeScene3D — interactive 3D crime-scene viewer (three.js + drei).
// Renders the same scene JSON as SceneMap: a single room, or a multi-room floor plan (walls with
// their doors and windows, as in the sample plan 2D/data/image.png). Furniture, doors and windows
// come from the scene (e.g. detected from an uploaded image); humanoid figures can be added and
// dragged anywhere.
//
// Props:
//   scene       — scene JSON (room, objects, people, evidence)
//   editable    — when true: drag items on the floor, add / rotate / remove
//   onMove      — (collection, index, [x, y, z]) => void        (called once, when a drag ends)
//   onEdit      — (edit) => void, edit is one of
//                   { type: "add_person", person }
//                   { type: "remove", coll, index }
//                   { type: "set", coll, index, field, value }
//   personLabel — (person) => string

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Text, Grid, Line } from "@react-three/drei";
import * as THREE from "three";
import { TurnLeftGlyph, TurnRightGlyph } from "./Glyph.jsx";
import { planOutline, planWalls, solidRuns, wallFrame, wallOpenings } from "./scenePlan.js";

const C = {
  floor: "#d6c597",
  wall: "#c8b97a",
  wallTop: "#b5a35e",
  furniture: "#b09a5c",
  suspect: "#C8321E",
  witness: "#2b4f7a",
  other: "#6f6a5a",
  evidence: "#e8c231",
  door: "#8a5a32",
  doorFrame: "#5e3d22",
  window: "#a0c8e0",
  windowFrame: "#f1ead6",
  grid: "#a89660",
  ambient: "#fff8e7",
  sky: "#1a1a2e",
  selected: "#ffcc00",
  skin: "#d8b08c",
  pants: "#2c2a36",
  areaLabel: "#7a6a3e",
};

const WALL_H = 3.0;
const WALL_T = 0.2; // outer walls
const WALL_T_INNER = 0.12;
const DOOR_H = 2.1;
const WIN_BASE = 0.9;
const WIN_H = 1.2;

const roleColor = (role) => (role === "suspect" ? C.suspect : role === "witness" ? C.witness : C.other);
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));

// ── Humanoid figure (front faces -z at facing 0) ──────────────────────────────

function Humanoid({ role, selected, label }) {
  const cloth = roleColor(role);
  const glow = selected ? { emissive: C.selected, emissiveIntensity: 0.35 } : {};
  const mat = (color) => <meshStandardMaterial color={color} roughness={0.85} {...glow} />;
  return (
    <group>
      {/* legs */}
      {[-0.1, 0.1].map((x) => (
        <mesh key={x} position={[x, 0.43, 0]} castShadow>
          <capsuleGeometry args={[0.08, 0.7, 6, 10]} />
          {mat(C.pants)}
        </mesh>
      ))}
      {/* torso */}
      <mesh position={[0, 1.2, 0]} scale={[1.15, 1, 0.7]} castShadow>
        <capsuleGeometry args={[0.16, 0.4, 8, 12]} />
        {mat(cloth)}
      </mesh>
      {/* arms */}
      {[-1, 1].map((s) => (
        <mesh key={s} position={[s * 0.28, 1.17, 0]} rotation={[0, 0, s * 0.08]} castShadow>
          <capsuleGeometry args={[0.055, 0.55, 6, 10]} />
          {mat(cloth)}
        </mesh>
      ))}
      {/* neck + head + nose (shows which way the person faces) */}
      <mesh position={[0, 1.59, 0]} castShadow>
        <cylinderGeometry args={[0.05, 0.055, 0.1, 10]} />
        {mat(C.skin)}
      </mesh>
      <mesh position={[0, 1.7, 0]} castShadow>
        <sphereGeometry args={[0.115, 20, 16]} />
        {mat(C.skin)}
      </mesh>
      <mesh position={[0, 1.69, -0.12]} rotation={[-Math.PI / 2, 0, 0]}>
        <coneGeometry args={[0.025, 0.06, 8]} />
        {mat("#b98f6c")}
      </mesh>
      {/* floor ring + facing arrow */}
      <mesh position={[0, 0.01, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.34, 0.4, 32]} />
        <meshBasicMaterial color={selected ? C.selected : cloth} transparent opacity={selected ? 0.95 : 0.55} />
      </mesh>
      <mesh position={[0, 0.012, -0.55]} rotation={[-Math.PI / 2, 0, 0]}>
        <coneGeometry args={[0.09, 0.2, 3]} />
        <meshBasicMaterial color={selected ? C.selected : "#e4d3a8"} />
      </mesh>
      {/* generous invisible hit area so the figure is easy to grab */}
      <mesh position={[0, 0.95, 0]}>
        <cylinderGeometry args={[0.45, 0.45, 1.9, 12]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>
      {label && (
        <Text
          position={[0, 2.05, 0]}
          fontSize={0.22}
          color="#14120F"
          anchorX="center"
          anchorY="bottom"
          outlineWidth={0.02}
          outlineColor="#e4d3a8"
        >
          {label}
        </Text>
      )}
    </group>
  );
}

// ── Furniture, shaped by type ─────────────────────────────────────────────────

const kindOf = (t = "") => {
  t = t.toLowerCase();
  if (/bed|cot|mattress/.test(t)) return "bed";
  if (/sofa|couch|settee/.test(t)) return "sofa";
  if (/chair|stool|bench/.test(t)) return "chair";
  if (/table|desk|counter/.test(t)) return "table";
  if (/\btv\b|television|monitor/.test(t)) return "tv";
  if (/cabinet|wardrobe|shelf|bookcase|almirah|fridge|refrigerator|cupboard|locker|dresser|rack|stove|oven/.test(t))
    return "cabinet";
  return "box";
};

function Part({ p, s, c }) {
  return (
    <mesh position={p} castShadow receiveShadow>
      <boxGeometry args={s} />
      <meshStandardMaterial color={c} roughness={0.85} metalness={0.05} />
    </mesh>
  );
}

function FurnitureShape({ type, size, color }) {
  const [w, h, d] = size;
  const kind = kindOf(type);
  const dark = new THREE.Color(color).multiplyScalar(0.75).getStyle();
  const legs = (top) =>
    [
      [-1, -1],
      [1, -1],
      [-1, 1],
      [1, 1],
    ].map(([sx, sz], i) => (
      <Part key={i} p={[sx * (w / 2 - 0.05), top / 2, sz * (d / 2 - 0.05)]} s={[0.06, top, 0.06]} c={dark} />
    ));

  if (kind === "table")
    return (
      <>
        <Part p={[0, h - 0.03, 0]} s={[w, 0.06, d]} c={color} />
        {legs(h - 0.06)}
      </>
    );
  if (kind === "chair")
    return (
      <>
        <Part p={[0, h * 0.5, 0]} s={[w, 0.06, d]} c={color} />
        <Part p={[0, h * 0.75, -d / 2 + 0.03]} s={[w, h * 0.5, 0.05]} c={color} />
        {legs(h * 0.5)}
      </>
    );
  if (kind === "bed")
    return (
      <>
        <Part p={[0, h * 0.22, 0]} s={[w, h * 0.44, d]} c={dark} />
        <Part p={[0, h * 0.44 + h * 0.15, 0.03]} s={[w - 0.06, h * 0.3, d - 0.1]} c="#efe6cf" />
        <Part p={[0, h * 0.74 + 0.04, -d / 2 + 0.3]} s={[w * 0.6, 0.1, 0.35]} c="#fffaf0" />
        <Part p={[0, h / 2, -d / 2 + 0.03]} s={[w, h, 0.06]} c={color} />
      </>
    );
  if (kind === "sofa")
    return (
      <>
        <Part p={[0, h * 0.22, 0]} s={[w, h * 0.44, d]} c={color} />
        <Part p={[0, h * 0.5, -d / 2 + 0.1]} s={[w, h, 0.2]} c={color} />
        {[-1, 1].map((s) => (
          <Part key={s} p={[s * (w / 2 - 0.09), h * 0.35, 0]} s={[0.18, h * 0.7, d]} c={dark} />
        ))}
      </>
    );
  if (kind === "tv")
    return (
      <>
        <Part p={[0, h * 0.05, 0]} s={[w * 0.3, h * 0.1, d * 0.6]} c={dark} />
        <Part p={[0, h * 0.55, 0]} s={[w, h * 0.85, Math.min(d, 0.06)]} c="#1c1c22" />
      </>
    );
  if (kind === "cabinet")
    return (
      <>
        <Part p={[0, h / 2, 0]} s={[w, h, d]} c={color} />
        <Part p={[0, h / 2, d / 2 + 0.005]} s={[0.02, h * 0.9, 0.01]} c={dark} />
        <Part p={[w * 0.08, h / 2, d / 2 + 0.02]} s={[0.04, 0.12, 0.03]} c="#d8d2c0" />
      </>
    );
  return <Part p={[0, h / 2, 0]} s={[w, h, d]} c={color} />;
}

function Furniture({ o, pos, selected, onDown, onClick, label }) {
  const color = o.locked ? C.suspect : C.furniture;
  const [w, h, d] = o.size;
  return (
    <group
      position={[pos[0], pos[1], pos[2]]}
      rotation={[0, (-(o.rot_y_deg || 0) * Math.PI) / 180, 0]}
      onPointerDown={onDown}
      onClick={onClick}
    >
      <FurnitureShape type={o.type} size={o.size} color={color} />
      {selected && (
        <mesh position={[0, h / 2, 0]}>
          <boxGeometry args={[w + 0.08, h + 0.08, d + 0.08]} />
          <meshBasicMaterial color={C.selected} transparent opacity={0.25} depthWrite={false} />
        </mesh>
      )}
      {label && (
        <Text
          position={[0, h + 0.15, 0]}
          fontSize={0.2}
          color="#14120F"
          anchorX="center"
          anchorY="bottom"
          outlineWidth={0.02}
          outlineColor="#e4d3a8"
        >
          {label}
        </Text>
      )}
    </group>
  );
}

function EvidenceMarker({ pos, label, selected, onDown, onClick }) {
  return (
    <group position={[pos[0], pos[1], pos[2]]} onPointerDown={onDown} onClick={onClick}>
      <mesh position={[0, 0.08, 0]}>
        <sphereGeometry args={[0.14, 16, 16]} />
        <meshStandardMaterial
          color={selected ? C.selected : C.evidence}
          emissive={C.evidence}
          emissiveIntensity={0.4}
        />
      </mesh>
      {label && (
        <Text position={[0, 0.38, 0]} fontSize={0.18} color={C.evidence} anchorX="center">
          {label}
        </Text>
      )}
    </group>
  );
}

// ── Room: plan walls with real openings, door leaves, window glass ────────────
// Walls come from scenePlan: a floor plan's own walls (outer and inner), or the four sides of a
// plain room. Each wall is drawn in its own frame: local x runs along it from a to b, local z is
// its left-hand normal.

function WallRun({ start, end, y0, y1, t }) {
  if (end - start < 0.02 || y1 - y0 < 0.02) return null;
  return (
    <mesh position={[(start + end) / 2, (y0 + y1) / 2, 0]} castShadow receiveShadow>
      <boxGeometry args={[end - start, y1 - y0, t]} />
      <meshStandardMaterial color={C.wall} roughness={0.9} />
    </mesh>
  );
}

function DoorPiece({ op, t }) {
  const fw = 0.06;
  const leaf = op.w - 2 * fw;
  const hinge = op.dir > 0 ? op.o + fw : op.o + op.w - fw;
  const open = Math.PI / 2 - 0.15; // leaf stands almost square to the wall, like the plan's arc
  const arc = Array.from({ length: 17 }, (_, k) => {
    const a = (k / 16) * (Math.PI / 2);
    return [hinge + op.dir * leaf * Math.cos(a), 0.015, op.side * leaf * Math.sin(a)];
  });
  return (
    <group>
      <Part p={[op.o + fw / 2, DOOR_H / 2, 0]} s={[fw, DOOR_H, t + 0.04]} c={C.doorFrame} />
      <Part p={[op.o + op.w - fw / 2, DOOR_H / 2, 0]} s={[fw, DOOR_H, t + 0.04]} c={C.doorFrame} />
      <Part p={[op.o + op.w / 2, DOOR_H - fw / 2, 0]} s={[op.w, fw, t + 0.04]} c={C.doorFrame} />
      <group position={[hinge, 0, 0]} rotation={[0, -op.dir * op.side * open, 0]}>
        <Part p={[(op.dir * leaf) / 2, (DOOR_H - fw) / 2, 0]} s={[leaf, DOOR_H - fw, 0.045]} c={C.door} />
        <Part p={[op.dir * (leaf - 0.1), 1.0, 0]} s={[0.04, 0.04, 0.14]} c="#d8d2c0" />
      </group>
      <Line points={[[hinge, 0.015, 0], ...arc]} color={C.doorFrame} lineWidth={1.2} transparent opacity={0.7} />
    </group>
  );
}

function WindowPiece({ op, t }) {
  const ft = 0.05;
  const cx = op.o + op.w / 2;
  return (
    <group>
      <mesh position={[cx, WIN_BASE + WIN_H / 2, 0]}>
        <planeGeometry args={[op.w, WIN_H]} />
        <meshStandardMaterial color={C.window} transparent opacity={0.45} side={THREE.DoubleSide} />
      </mesh>
      <Part p={[cx, WIN_BASE + ft / 2, 0]} s={[op.w, ft, t + 0.04]} c={C.windowFrame} />
      <Part p={[cx, WIN_BASE + WIN_H - ft / 2, 0]} s={[op.w, ft, t + 0.04]} c={C.windowFrame} />
      <Part p={[op.o + ft / 2, WIN_BASE + WIN_H / 2, 0]} s={[ft, WIN_H, t + 0.04]} c={C.windowFrame} />
      <Part p={[op.o + op.w - ft / 2, WIN_BASE + WIN_H / 2, 0]} s={[ft, WIN_H, t + 0.04]} c={C.windowFrame} />
      <Part p={[cx, WIN_BASE + WIN_H / 2, 0]} s={[ft * 0.6, WIN_H, 0.03]} c={C.windowFrame} />
    </group>
  );
}

function PlanWallMesh({ wall }) {
  const { len, ux, uz } = wallFrame(wall);
  const t = wall.exterior === false ? WALL_T_INNER : WALL_T;
  const ops = wallOpenings(wall);
  return (
    <group position={[wall.a[0], 0, wall.a[1]]} rotation={[0, Math.atan2(-uz, ux), 0]}>
      {/* solid runs reach half a thickness past each end so corners close */}
      {solidRuns(len, ops, t / 2).map(([s0, s1]) => (
        <WallRun key={`r${s0}`} start={s0} end={s1} y0={0} y1={WALL_H} t={t} />
      ))}
      {ops.map((op) =>
        op.kind === "window" ? (
          <group key={op.id}>
            <WallRun start={op.o} end={op.o + op.w} y0={0} y1={WIN_BASE} t={t} />
            <WallRun start={op.o} end={op.o + op.w} y0={WIN_BASE + WIN_H} y1={WALL_H} t={t} />
            <WindowPiece op={op} t={t} />
          </group>
        ) : (
          <group key={op.id}>
            <WallRun start={op.o} end={op.o + op.w} y0={DOOR_H} y1={WALL_H} t={t} />
            <DoorPiece op={op} t={t} />
          </group>
        ),
      )}
    </group>
  );
}

function Room({ room }) {
  const floor = useMemo(() => {
    const shape = new THREE.Shape(planOutline(room).map(([x, z]) => new THREE.Vector2(x, -z)));
    return new THREE.ShapeGeometry(shape);
  }, [room]);
  return (
    <group>
      <mesh geometry={floor} receiveShadow rotation={[-Math.PI / 2, 0, 0]}>
        <meshStandardMaterial color={C.floor} roughness={0.95} side={THREE.DoubleSide} />
      </mesh>
      {planWalls(room).map((w) => (
        <PlanWallMesh key={w.id} wall={w} />
      ))}
      {(room.areas || []).map((a) => (
        <Text
          key={a.id}
          position={[(a.rect[0] + a.rect[2]) / 2, 0.02, (a.rect[1] + a.rect[3]) / 2]}
          rotation={[-Math.PI / 2, 0, 0]}
          fontSize={0.32}
          color={C.areaLabel}
          anchorX="center"
          anchorY="middle"
        >
          {a.name}
        </Text>
      ))}
    </group>
  );
}

// ── Scene content: selection, floor-plane dragging, camera ───────────────────

function SceneContent({ scene, editable, onMove, personLabel, sel, setSel }) {
  const { camera, gl } = useThree();
  const [drag, setDrag] = useState(null); // { coll, index, dx, dz }
  const [live, setLive] = useState(null); // { coll, index, pos }
  const liveRef = useRef(null);
  const room = scene.room;

  // While dragging, follow the pointer across the floor plane (works anywhere in the room).
  useEffect(() => {
    if (!drag) return undefined;
    const el = gl.domElement;
    const rc = new THREE.Raycaster();
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const hit = new THREE.Vector3();
    const ndc = new THREE.Vector2();
    const item = scene[drag.coll]?.[drag.index];
    const half = drag.coll === "objects" && item ? [item.size[0] / 2, item.size[2] / 2] : [0.25, 0.25];

    const move = (ev) => {
      const r = el.getBoundingClientRect();
      ndc.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
      rc.setFromCamera(ndc, camera);
      if (!rc.ray.intersectPlane(plane, hit)) return;
      const x = clamp(hit.x + drag.dx, half[0], room.width_m - half[0]);
      const z = clamp(hit.z + drag.dz, half[1], room.depth_m - half[1]);
      const next = { coll: drag.coll, index: drag.index, pos: [x, item?.pos?.[1] || 0, z] };
      liveRef.current = next;
      setLive(next);
    };
    const up = () => {
      const l = liveRef.current;
      liveRef.current = null;
      setDrag(null);
      setLive(null);
      if (l) onMove?.(l.coll, l.index, l.pos);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag]);

  const startDrag = useCallback(
    (coll, index, item) => (e) => {
      e.stopPropagation();
      setSel({ coll, index });
      if (!editable || item.locked) return;
      const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
      const p = new THREE.Vector3();
      const hit = e.ray.intersectPlane(plane, p);
      setDrag({
        coll,
        index,
        dx: hit ? item.pos[0] - p.x : 0,
        dz: hit ? item.pos[2] - p.z : 0,
      });
    },
    [editable, setSel],
  );

  const swallowClick = useCallback((e) => e.stopPropagation(), []);
  const posOf = (coll, index, item) => (live && live.coll === coll && live.index === index ? live.pos : item.pos);
  const isSel = (coll, index) => sel?.coll === coll && sel?.index === index;

  return (
    <>
      <ambientLight intensity={0.7} color={C.ambient} />
      <directionalLight position={[room.width_m / 2, 6, room.depth_m / 2]} intensity={1.2} castShadow shadow-mapSize={[2048, 2048]} />
      <pointLight position={[room.width_m / 2, 2.5, room.depth_m / 2]} intensity={0.4} color="#ffe8c0" />

      <Room room={room} />

      {(scene.objects || []).map((o, i) => (
        <Furniture
          key={o.id}
          o={o}
          pos={posOf("objects", i, o)}
          label={o.type}
          selected={isSel("objects", i)}
          onDown={startDrag("objects", i, o)}
          onClick={swallowClick}
        />
      ))}

      {(scene.people || []).map((p, i) => (
        <group
          key={p.id}
          position={posOf("people", i, p)}
          rotation={[0, (-(p.facing_deg || 0) * Math.PI) / 180, 0]}
          onPointerDown={startDrag("people", i, p)}
          onClick={swallowClick}
        >
          <Humanoid role={p.role} selected={isSel("people", i)} label={personLabel ? personLabel(p) : p.id} />
        </group>
      ))}

      {(scene.evidence || []).map((ev, i) => (
        <EvidenceMarker
          key={ev.id}
          pos={posOf("evidence", i, ev)}
          label={ev.label}
          selected={isSel("evidence", i)}
          onDown={startDrag("evidence", i, ev)}
          onClick={swallowClick}
        />
      ))}

      <Grid
        args={[room.width_m + 4, room.depth_m + 4]}
        position={[room.width_m / 2, -0.001, room.depth_m / 2]}
        cellSize={1}
        cellThickness={0.5}
        cellColor={C.grid}
        sectionSize={5}
        sectionThickness={1}
        sectionColor={C.wallTop}
        fadeDistance={40}
        fadeStrength={1}
        followCamera={false}
        infiniteGrid={false}
      />

      {/* click on empty floor deselects */}
      <mesh position={[room.width_m / 2, -0.01, room.depth_m / 2]} rotation={[-Math.PI / 2, 0, 0]} onClick={() => setSel(null)}>
        <planeGeometry args={[100, 100]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      <OrbitControls
        makeDefault
        enabled={!drag}
        target={[room.width_m / 2, 0, room.depth_m / 2]}
        maxPolarAngle={Math.PI / 2}
        minDistance={2}
        maxDistance={50}
        enableDamping
        dampingFactor={0.08}
      />
    </>
  );
}

// ── Public component ─────────────────────────────────────────────────────────

export default function CrimeScene3D({ scene, editable = false, onMove, onEdit, personLabel }) {
  const [sel, setSel] = useState(null);
  if (!scene?.room) return null;

  const room = scene.room;
  const cx = room.width_m / 2;
  const cz = room.depth_m / 2;
  const dist = Math.max(room.width_m, room.depth_m) * 1.5;

  const selItem = sel ? scene[sel.coll]?.[sel.index] : null;
  const selName = !selItem
    ? ""
    : sel.coll === "people"
      ? personLabel?.(selItem) || selItem.id
      : sel.coll === "evidence"
        ? selItem.label
        : selItem.type;
  const canEdit = editable && !!onEdit;

  const addPerson = (role) => {
    const n = (scene.people || []).length;
    const person = {
      id: `${role}_${Date.now().toString(36)}`,
      role,
      pos: [clamp(cx + (n % 4) * 0.7 - 1, 0.3, room.width_m - 0.3), 0, clamp(cz + Math.floor(n / 4) * 0.7, 0.3, room.depth_m - 0.3)],
      facing_deg: 0,
      eye_height_m: 1.6,
    };
    onEdit({ type: "add_person", person });
    setSel({ coll: "people", index: n });
  };

  const rotate = (delta) => {
    if (!selItem || sel.coll === "evidence") return;
    const field = sel.coll === "people" ? "facing_deg" : "rot_y_deg";
    const cur = Number(selItem[field] || 0);
    onEdit({ type: "set", coll: sel.coll, index: sel.index, field, value: (((cur + delta) % 360) + 360) % 360 });
  };

  const remove = () => {
    if (!selItem) return;
    onEdit({ type: "remove", coll: sel.coll, index: sel.index });
    setSel(null);
  };

  return (
    <div className="scene3d-root">
      {canEdit && (
        <div className="scene3d-toolbar">
          <span className="tb-label">Add person</span>
          {["witness", "suspect", "other"].map((role) => (
            <button key={role} type="button" className="scene-view-btn" onClick={() => addPerson(role)}>
              ＋ {cap(role)}
            </button>
          ))}
          {selItem && (
            <>
              <span className="tb-sep" />
              <span className="tb-label">Selected: {selName}</span>
              {sel.coll !== "evidence" && (
                <>
                  <button type="button" className="scene-view-btn" title="Turn left 45°" aria-label="Turn left 45°" onClick={() => rotate(-45)}>
                    <TurnLeftGlyph size={16} />
                  </button>
                  <button type="button" className="scene-view-btn" title="Turn right 45°" aria-label="Turn right 45°" onClick={() => rotate(45)}>
                    <TurnRightGlyph size={16} />
                  </button>
                </>
              )}
              <button type="button" className="scene-view-btn" onClick={remove}>
                Remove
              </button>
            </>
          )}
        </div>
      )}

      <div className="scene3d-canvas" style={{ touchAction: "none" }}>
        <Canvas
          shadows
          camera={{ position: [cx + dist * 0.6, dist * 0.7, cz + dist * 0.8], fov: 45, near: 0.1, far: 200 }}
          gl={{ antialias: true, alpha: false }}
          style={{ background: C.sky }}
        >
          <Suspense fallback={null}>
            <SceneContent scene={scene} editable={editable} onMove={onMove} personLabel={personLabel} sel={sel} setSel={setSel} />
          </Suspense>
        </Canvas>

        <div className="scene3d-legend">
          <span className="legend-dot" style={{ background: C.suspect }} /> Suspect
          <span className="legend-dot" style={{ background: C.witness }} /> Witness
          <span className="legend-dot" style={{ background: C.other }} /> Other
          <span className="legend-dot" style={{ background: C.evidence }} /> Evidence
          <span className="legend-dot" style={{ background: C.furniture }} /> Furniture
          <span className="legend-dot" style={{ background: C.door }} /> Door
          <span className="legend-dot" style={{ background: C.window }} /> Window
        </div>
        <div className="scene3d-hint">
          {canEdit ? "Click to select · drag to move · drag empty space to orbit · scroll to zoom" : "Drag to orbit · scroll to zoom · right-drag to pan"}
        </div>
      </div>
    </div>
  );
}
