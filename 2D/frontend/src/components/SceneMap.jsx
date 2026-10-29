// Top-down crime-scene layout drawn as paper cut-outs on a sheet: a single room or a multi-room
// floor plan (walls, door swings, windows; see scenePlan.js). Objects and people can be
// dragged (when `editable`); dropping calls onMove(collection, index, [x, 0, z]).
import { useRef, useState } from "react";
import { planOutline, planWalls, solidRuns, wallFrame, wallOpenings } from "./scenePlan.js";

const INK = "#14120F";
const RED = "#C8321E";

export default function SceneMap({ scene, editable = false, onMove, labelFor, personLabel, showAnalysis, analysis }) {
  const svgRef = useRef(null);
  const [drag, setDrag] = useState(null); // {coll, index, x, z}
  if (!scene?.room) return null;
  const W = scene.room.width_m;
  const D = scene.room.depth_m;
  const pad = 0.6;
  const vb = `${-pad} ${-pad} ${W + pad * 2} ${D + pad * 2}`;
  const unit = Math.max(W, D) / 40; // stroke unit in metres

  const toWorld = (e) => {
    const svg = svgRef.current;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    return [Math.min(W, Math.max(0, p.x)), Math.min(D, Math.max(0, p.y))];
  };
  const startDrag = (coll, index, item) => (e) => {
    if (!editable || item.locked) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setDrag({ coll, index, x: item.pos[0], z: item.pos[2] });
  };
  const moveDrag = (e) => {
    if (!drag) return;
    const [x, z] = toWorld(e);
    setDrag((d) => ({ ...d, x, z }));
  };
  const endDrag = () => {
    if (!drag) return;
    const snap = (v) => Math.round(v * 4) / 4;
    onMove?.(drag.coll, drag.index, [snap(drag.x), 0, snap(drag.z)]);
    setDrag(null);
  };
  const posOf = (coll, i, item) => (drag && drag.coll === coll && drag.index === i ? [drag.x, drag.z] : [item.pos[0], item.pos[2]]);

  const witness = scene.people?.find((p) => p.role === "witness");
  const suspect = scene.people?.find((p) => p.role === "suspect");

  return (
    <svg
      ref={svgRef}
      className={`scene-map ${editable ? "editable" : ""}`}
      viewBox={vb}
      onPointerMove={moveDrag}
      onPointerUp={endDrag}
      onPointerLeave={endDrag}
      role="img"
      aria-label="Scene layout"
    >
      {/* metre grid */}
      {Array.from({ length: Math.floor(W) + 1 }, (_, i) => (
        <line key={`gx${i}`} x1={i} y1={0} x2={i} y2={D} stroke={INK} strokeOpacity=".08" strokeWidth={unit * 0.15} />
      ))}
      {Array.from({ length: Math.floor(D) + 1 }, (_, i) => (
        <line key={`gz${i}`} x1={0} y1={i} x2={W} y2={i} stroke={INK} strokeOpacity=".08" strokeWidth={unit * 0.15} />
      ))}
      <polygon points={planOutline(scene.room).map((p) => p.join(",")).join(" ")} fill={INK} fillOpacity=".03" />
      {(scene.room.areas || []).map((a) => (
        <text
          key={a.id}
          x={(a.rect[0] + a.rect[2]) / 2}
          y={(a.rect[1] + a.rect[3]) / 2}
          textAnchor="middle"
          fontSize={unit * 1.3}
          fill={INK}
          fillOpacity=".4"
          className="scene-label"
        >
          {a.name}
        </text>
      ))}
      {planWalls(scene.room).map((wall) => {
        const { len, ux, uz } = wallFrame(wall);
        const ops = wallOpenings(wall);
        const at = (s, n = 0) => [wall.a[0] + ux * s - uz * n, wall.a[1] + uz * s + ux * n];
        const sw = unit * (wall.exterior === false ? 0.35 : 0.6);
        return (
          <g key={wall.id}>
            {solidRuns(len, ops, sw / 2).map(([s0, s1]) => {
              const [x1, y1] = at(s0);
              const [x2, y2] = at(s1);
              return <line key={s0} x1={x1} y1={y1} x2={x2} y2={y2} stroke={INK} strokeWidth={sw} />;
            })}
            {ops.map((op) => {
              if (op.kind === "window") {
                const g = sw * 0.35;
                return [-g, g].map((n) => {
                  const [x1, y1] = at(op.o, n);
                  const [x2, y2] = at(op.o + op.w, n);
                  return <line key={`${op.id}${n}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke={INK} strokeWidth={unit * 0.12} />;
                });
              }
              // door: leaf standing open plus the swing arc, as drawn on a plan
              const h = op.dir > 0 ? op.o : op.o + op.w;
              const [hx, hy] = at(h);
              const [lx, ly] = at(h, op.side * op.w);
              const [cx, cy] = at(h + op.dir * op.w);
              const sweep = op.dir * op.side > 0 ? 1 : 0;
              return (
                <g key={op.id} stroke={INK} fill="none">
                  <line x1={hx} y1={hy} x2={lx} y2={ly} strokeWidth={unit * 0.2} />
                  <path d={`M${cx} ${cy} A${op.w} ${op.w} 0 0 ${sweep} ${lx} ${ly}`} strokeWidth={unit * 0.1} strokeOpacity=".6" />
                </g>
              );
            })}
          </g>
        );
      })}

      {/* sight line (staff only: shows the analysis) */}
      {showAnalysis && witness && suspect && (
        <line
          x1={witness.pos[0]}
          y1={witness.pos[2]}
          x2={suspect.pos[0]}
          y2={suspect.pos[2]}
          stroke={analysis?.line_of_sight === "blocked" ? RED : INK}
          strokeWidth={unit * 0.3}
          strokeDasharray={`${unit * 0.8} ${unit * 0.5}`}
        />
      )}

      {(scene.objects || []).map((o, i) => {
        const [x, z] = posOf("objects", i, o);
        const label = labelFor ? labelFor(o) : o.type;
        return (
          <g
            key={o.id}
            transform={`translate(${x} ${z}) rotate(${o.rot_y_deg || 0})`}
            onPointerDown={startDrag("objects", i, o)}
            className={editable && !o.locked ? "draggable" : undefined}
          >
            <rect
              x={-o.size[0] / 2}
              y={-o.size[2] / 2}
              width={o.size[0]}
              height={o.size[2]}
              fill={o.type === "road" ? "rgba(20,18,15,.06)" : "#d6c597"}
              stroke={o.locked ? RED : INK}
              strokeWidth={unit * (o.locked ? 0.35 : 0.22)}
            />
            {label && o.type !== "road" && (
              <text
                y={unit * 0.4}
                textAnchor="middle"
                fontSize={unit * 1.25}
                fill={INK}
                className="scene-label"
                transform={o.size[0] < 1.2 && o.size[2] > o.size[0] ? "rotate(-90)" : undefined}
              >
                {label}
              </text>
            )}
          </g>
        );
      })}

      {(scene.evidence || []).map((ev) => (
        <g key={ev.id} transform={`translate(${ev.pos[0]} ${ev.pos[2]})`}>
          <path d={`M0 ${-unit} L${unit * 0.9} ${unit * 0.6} L${-unit * 0.9} ${unit * 0.6}Z`} fill="none" stroke={RED} strokeWidth={unit * 0.25} />
        </g>
      ))}

      {(scene.people || []).map((p, i) => {
        const [x, z] = posOf("people", i, p);
        const r = unit * 1.1;
        const a = ((p.facing_deg || 0) * Math.PI) / 180;
        return (
          <g key={p.id} transform={`translate(${x} ${z})`} onPointerDown={startDrag("people", i, p)} className={editable ? "draggable" : undefined}>
            <circle r={r} fill={p.role === "suspect" ? RED : p.role === "witness" ? INK : "#E4D3A8"} stroke={INK} strokeWidth={unit * 0.2} />
            <line x1="0" y1="0" x2={Math.sin(a) * r * 2} y2={-Math.cos(a) * r * 2} stroke={INK} strokeWidth={unit * 0.25} />
            <text y={-r * 1.5} textAnchor="middle" fontSize={unit * 1.2} fill={INK} className="scene-label">
              {personLabel ? personLabel(p) : p.id}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
