// CrimeScene3D — fully interactive 3D crime scene viewer using Three.js + drei.
// Renders the same scene JSON used by SceneMap but in 3D with orbit/select controls.
//
// Props:
//   scene   — scene JSON (same schema as SceneMap)
//   editable— boolean; when true shows TransformControls on selected objects
//   onMove  — (collection, index, [x, y, z]) => void

import { Suspense, useRef, useState, useCallback, useEffect } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import {
  OrbitControls,
  TransformControls,
  Text,
  Grid,
  Environment,
  Html,
  useTexture,
} from "@react-three/drei";
import * as THREE from "three";

// ── colour palette matching the paper/ink UI ───────────────────────────────
const C = {
  floor:     "#d6c597",
  wall:      "#c8b97a",
  wallTop:   "#b5a35e",
  furniture: "#b09a5c",
  suspect:   "#C8321E",
  witness:   "#14120F",
  other:     "#8e7c52",
  evidence:  "#e8c231",
  door:      "#e4d3a8",
  window:    "#a0c8e0",
  grid:      "#a89660",
  ambient:   "#fff8e7",
  sky:       "#1a1a2e",
  selected:  "#ffcc00",
};

// ── Helpers ────────────────────────────────────────────────────────────────

function Box({ pos, size, color, label, selected, onClick, wireframe = false }) {
  const [x, y, z] = pos;
  const [w, h, d] = size;
  return (
    <group position={[x, y + h / 2, z]} onClick={onClick}>
      <mesh castShadow receiveShadow>
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial
          color={selected ? C.selected : color}
          roughness={0.85}
          metalness={0.05}
          wireframe={wireframe}
        />
      </mesh>
      {label && (
        <Text
          position={[0, h / 2 + 0.15, 0]}
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
      {selected && (
        <mesh>
          <boxGeometry args={[w + 0.04, h + 0.04, d + 0.04]} />
          <meshStandardMaterial color={C.selected} transparent opacity={0.15} />
        </mesh>
      )}
    </group>
  );
}

function PersonFigure({ pos, facingDeg, color, label, selected, onClick }) {
  const [x, , z] = pos;
  const bodyH = 1.6;
  const headR = 0.18;
  const angle = (facingDeg * Math.PI) / 180;
  return (
    <group position={[x, 0, z]} rotation={[0, -angle, 0]} onClick={onClick}>
      {/* Body */}
      <mesh position={[0, bodyH / 2, 0]} castShadow>
        <capsuleGeometry args={[0.2, bodyH - 0.4, 8, 8]} />
        <meshStandardMaterial color={selected ? C.selected : color} roughness={0.9} />
      </mesh>
      {/* Head */}
      <mesh position={[0, bodyH + headR, 0]} castShadow>
        <sphereGeometry args={[headR, 16, 16]} />
        <meshStandardMaterial color={selected ? C.selected : color} roughness={0.9} />
      </mesh>
      {/* Facing arrow */}
      <mesh position={[0, bodyH * 0.8, -0.3]} rotation={[Math.PI / 2, 0, 0]}>
        <coneGeometry args={[0.07, 0.25, 8]} />
        <meshStandardMaterial color="#e4d3a8" />
      </mesh>
      {label && (
        <Text
          position={[0, bodyH + headR * 2 + 0.1, 0]}
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

function EvidenceMarker({ pos, label, selected, onClick }) {
  const [x, , z] = pos;
  return (
    <group position={[x, 0, z]} onClick={onClick}>
      <mesh position={[0, 0.06, 0]}>
        <sphereGeometry args={[0.12, 16, 16]} />
        <meshStandardMaterial color={selected ? C.selected : C.evidence} emissive={C.evidence} emissiveIntensity={0.4} />
      </mesh>
      {label && (
        <Text position={[0, 0.32, 0]} fontSize={0.18} color={C.evidence} anchorX="center">
          {label}
        </Text>
      )}
    </group>
  );
}

function Room({ room }) {
  const W = room.width_m;
  const D = room.depth_m;
  const wallH = 3.0;
  const wallT = 0.18;
  const doors = room.doors || [];
  const windows = room.windows || [];

  // Build walls as sets of sub-segments with gaps for doors/windows
  const wallSegments = [];

  const makeWallSegments = (wallName, totalLength, isNS) => {
    // Gather openings on this wall
    const openings = [
      ...doors.filter((d) => d.wall === wallName),
      ...windows.filter((w) => w.wall === wallName),
    ].map((o) => ({ start: o.offset_m, end: o.offset_m + o.width_m, isDoor: "offset_m" in o && !("eye_height_m" in o) }));
    openings.sort((a, b) => a.start - b.start);

    // Fill gaps between openings
    let cursor = 0;
    const segs = [];
    for (const op of openings) {
      if (cursor < op.start) segs.push({ start: cursor, end: op.start });
      cursor = op.end;
    }
    if (cursor < totalLength) segs.push({ start: cursor, end: totalLength });
    return segs.map((s) => ({ wallName, start: s.start, length: s.end - s.start, isNS }));
  };

  wallSegments.push(...makeWallSegments("north", W, false));
  wallSegments.push(...makeWallSegments("south", W, false));
  wallSegments.push(...makeWallSegments("west", D, true));
  wallSegments.push(...makeWallSegments("east", D, true));

  return (
    <group>
      {/* Floor */}
      <mesh receiveShadow rotation={[-Math.PI / 2, 0, 0]} position={[W / 2, 0, D / 2]}>
        <planeGeometry args={[W, D]} />
        <meshStandardMaterial color={C.floor} roughness={0.95} />
      </mesh>

      {/* Wall segments */}
      {wallSegments.map((seg, i) => {
        let px, pz, geoW;
        if (seg.wallName === "north") {
          pz = 0; px = seg.start + seg.length / 2; geoW = seg.length;
          return (
            <mesh key={i} position={[px, wallH / 2, pz]} castShadow receiveShadow>
              <boxGeometry args={[geoW, wallH, wallT]} />
              <meshStandardMaterial color={C.wall} roughness={0.9} />
            </mesh>
          );
        }
        if (seg.wallName === "south") {
          pz = D; px = seg.start + seg.length / 2; geoW = seg.length;
          return (
            <mesh key={i} position={[px, wallH / 2, pz]} castShadow receiveShadow>
              <boxGeometry args={[geoW, wallH, wallT]} />
              <meshStandardMaterial color={C.wall} roughness={0.9} />
            </mesh>
          );
        }
        if (seg.wallName === "west") {
          px = 0; pz = seg.start + seg.length / 2; geoW = seg.length;
          return (
            <mesh key={i} position={[px, wallH / 2, pz]} castShadow receiveShadow>
              <boxGeometry args={[wallT, wallH, geoW]} />
              <meshStandardMaterial color={C.wall} roughness={0.9} />
            </mesh>
          );
        }
        // east
        px = W; pz = seg.start + seg.length / 2; geoW = seg.length;
        return (
          <mesh key={i} position={[px, wallH / 2, pz]} castShadow receiveShadow>
            <boxGeometry args={[wallT, wallH, geoW]} />
            <meshStandardMaterial color={C.wall} roughness={0.9} />
          </mesh>
        );
      })}

      {/* Window indicators (blue tinted gaps) */}
      {windows.map((w) => {
        let px, pz, geoW, rotY = 0;
        const winH = 1.2, winBase = 0.9;
        if (w.wall === "north") { pz = 0; px = w.offset_m + w.width_m / 2; geoW = w.width_m; }
        else if (w.wall === "south") { pz = D; px = w.offset_m + w.width_m / 2; geoW = w.width_m; }
        else if (w.wall === "west") { px = 0; pz = w.offset_m + w.width_m / 2; geoW = w.width_m; rotY = Math.PI / 2; }
        else { px = W; pz = w.offset_m + w.width_m / 2; geoW = w.width_m; rotY = Math.PI / 2; }
        return (
          <mesh key={w.id} position={[px, winBase + winH / 2, pz]} rotation={[0, rotY, 0]}>
            <planeGeometry args={[geoW, winH]} />
            <meshStandardMaterial color={C.window} transparent opacity={0.5} side={THREE.DoubleSide} />
          </mesh>
        );
      })}
    </group>
  );
}

// ── Selection-aware transform wrapper ─────────────────────────────────────

function SelectableTransform({ children, selected, onMove, position }) {
  const objRef = useRef();
  const { camera, gl } = useThree();

  return (
    <group ref={objRef} position={position}>
      {selected && (
        <TransformControls
          object={objRef}
          mode="translate"
          onObjectChange={() => {
            if (objRef.current) {
              const p = objRef.current.position;
              onMove?.([p.x, p.y, p.z]);
            }
          }}
        />
      )}
      {children}
    </group>
  );
}

// ── Main 3D Scene content ──────────────────────────────────────────────────

function SceneContent({ scene, editable, onMove, personLabel }) {
  const [sel, setSel] = useState(null); // {coll, index}

  const selectItem = useCallback((coll, index) => (e) => {
    e.stopPropagation();
    setSel((s) => s?.coll === coll && s?.index === index ? null : { coll, index });
  }, []);

  const moveItem = useCallback((coll, index) => ([x, y, z]) => {
    onMove?.(coll, index, [x, y, z]);
  }, [onMove]);

  if (!scene?.room) return null;

  return (
    <>
      {/* Lighting */}
      <ambientLight intensity={0.7} color={C.ambient} />
      <directionalLight
        position={[scene.room.width_m / 2, 6, scene.room.depth_m / 2]}
        intensity={1.2}
        castShadow
        shadow-mapSize={[2048, 2048]}
      />
      <pointLight position={[scene.room.width_m / 2, 2.5, scene.room.depth_m / 2]} intensity={0.4} color="#ffe8c0" />

      {/* Room structure */}
      <Room room={scene.room} />

      {/* Objects / furniture */}
      {(scene.objects || []).map((o, i) => {
        const isSel = sel?.coll === "objects" && sel?.index === i;
        return (
          <Box
            key={o.id}
            pos={o.pos}
            size={o.size}
            color={o.locked ? C.suspect : C.furniture}
            label={o.type}
            selected={isSel}
            onClick={selectItem("objects", i)}
          />
        );
      })}

      {/* People */}
      {(scene.people || []).map((p, i) => {
        const isSel = sel?.coll === "people" && sel?.index === i;
        const color = p.role === "suspect" ? C.suspect : p.role === "witness" ? C.witness : C.other;
        const label = personLabel ? personLabel(p) : p.id;
        return (
          <PersonFigure
            key={p.id}
            pos={p.pos}
            facingDeg={p.facing_deg || 0}
            color={color}
            label={label}
            selected={isSel}
            onClick={selectItem("people", i)}
          />
        );
      })}

      {/* Evidence */}
      {(scene.evidence || []).map((ev, i) => {
        const isSel = sel?.coll === "evidence" && sel?.index === i;
        return (
          <EvidenceMarker
            key={ev.id}
            pos={ev.pos}
            label={ev.label}
            selected={isSel}
            onClick={selectItem("evidence", i)}
          />
        );
      })}

      {/* Grid helper */}
      <Grid
        args={[scene.room.width_m + 4, scene.room.depth_m + 4]}
        position={[scene.room.width_m / 2, -0.001, scene.room.depth_m / 2]}
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

      {/* Click on background deselects */}
      <mesh
        position={[scene.room.width_m / 2, -0.01, scene.room.depth_m / 2]}
        rotation={[-Math.PI / 2, 0, 0]}
        onClick={() => setSel(null)}
      >
        <planeGeometry args={[100, 100]} />
        <meshBasicMaterial transparent opacity={0} />
      </mesh>

      {/* Camera controls */}
      <OrbitControls
        makeDefault
        target={[scene.room.width_m / 2, 0, scene.room.depth_m / 2]}
        maxPolarAngle={Math.PI / 2}
        minDistance={2}
        maxDistance={50}
        enableDamping
        dampingFactor={0.08}
      />
    </>
  );
}

// ── Public component ───────────────────────────────────────────────────────

export default function CrimeScene3D({ scene, editable = false, onMove, personLabel }) {
  if (!scene?.room) return null;

  const cx = scene.room.width_m / 2;
  const cz = scene.room.depth_m / 2;
  const dist = Math.max(scene.room.width_m, scene.room.depth_m) * 1.5;

  return (
    <div className="scene3d-canvas">
      <Canvas
        shadows
        camera={{
          position: [cx + dist * 0.6, dist * 0.7, cz + dist * 0.8],
          fov: 45,
          near: 0.1,
          far: 200,
        }}
        gl={{ antialias: true, alpha: false }}
        style={{ background: C.sky }}
      >
        <Suspense fallback={null}>
          <SceneContent
            scene={scene}
            editable={editable}
            onMove={onMove}
            personLabel={personLabel}
          />
        </Suspense>
      </Canvas>

      {/* Legend */}
      <div className="scene3d-legend">
        <span className="legend-dot" style={{ background: C.suspect }} /> Suspect
        <span className="legend-dot" style={{ background: C.witness }} /> Witness
        <span className="legend-dot" style={{ background: C.evidence }} /> Evidence
        <span className="legend-dot" style={{ background: C.furniture }} /> Object
      </div>

      <div className="scene3d-hint">
        🖱 Drag to orbit · Scroll to zoom · Right-drag to pan
      </div>
    </div>
  );
}
