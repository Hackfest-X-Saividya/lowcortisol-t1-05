// Paper pieces pinned to the wall. Every piece has a torn, ragged edge (seeded), a slight
// tilt, faint grain and crease lines, and a soft shadow lifting it off the wall.
import { useMemo } from "react";
import { creaseLayer, tornClip } from "../lib/torn.js";
import { Pin } from "./Board.jsx";

/**
 * pins: [{ id, x: "50%", tone: "red" | "ink" }]
 * rotate: degrees (keep within +-1.5 for notes, +-1 for panels, 0 for the centre sheet)
 */
export function Paper({
  seed,
  rotate = 0,
  pins = [],
  jag = 3.2,
  side = 1.6,
  className = "",
  bodyClass = "",
  style,
  bodyStyle,
  children,
  as: Tag = "div",
  ...rest
}) {
  const clip = useMemo(() => tornClip(seed, { jag, side }), [seed, jag, side]);
  const crease = useMemo(() => creaseLayer(seed), [seed]);
  return (
    <Tag className={`paper ${className}`} style={{ "--rot": `${rotate}deg`, ...style }} {...rest}>
      <div className={`paper-body ${bodyClass}`} style={{ clipPath: clip, backgroundImage: `${crease}, var(--grain)`, ...bodyStyle }}>
        {children}
      </div>
      {pins.map((p) => (
        <Pin key={p.id || p.x} id={p.id} tone={p.tone || "red"} style={{ left: p.x ?? "50%", top: p.y }} />
      ))}
    </Tag>
  );
}

/** A torn manila strip with a short typewriter label. */
export function Strip({ seed, rotate = 0, pins, children, className = "", ink = true, ...rest }) {
  return (
    <Paper seed={seed} rotate={rotate} pins={pins} jag={2.6} className={`strip ${className}`} {...rest}>
      <span className={ink ? "ink" : undefined}>{children}</span>
    </Paper>
  );
}

/** A red rubber-stamped tag stuck on the wall (solid red fill). */
export function Stamp({ children, rotate = -1, as: Tag = "div", className = "", ...rest }) {
  return (
    <Tag className={`stamp ${className}`} style={{ "--rot": `${rotate}deg` }} {...rest}>
      <span className="stamp-text">{children}</span>
    </Tag>
  );
}

/** Square typewriter button with a 1px ink hairline, at least 44px high. */
export function InkButton({ children, className = "", glyph, selected, variant, ...rest }) {
  return (
    <button type="button" className={`ink-btn ${variant ? `ink-btn-${variant}` : ""} ${selected ? "is-selected" : ""} ${className}`} {...rest}>
      <span className="ink">{children}</span>
      {glyph}
    </button>
  );
}
