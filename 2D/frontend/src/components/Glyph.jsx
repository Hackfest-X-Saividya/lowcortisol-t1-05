// Fine-pen glyphs: single 1.5px stroke, square ends, mitred joins. No icon library.
const base = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "square",
  strokeLinejoin: "miter",
};

export function PauseGlyph({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true" {...base}>
      <path d="M6 3.5V14.5M12 3.5V14.5" />
    </svg>
  );
}

export function ArrowGlyph({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true" {...base}>
      <path d="M3 9H14.5M10 4.5L14.5 9L10 13.5" />
    </svg>
  );
}

export function BackGlyph({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true" {...base}>
      <path d="M15 9H3.5M8 4.5L3.5 9L8 13.5" />
    </svg>
  );
}

export function PinGlyph({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true" {...base}>
      <path d="M9 2.5A3.5 3.5 0 1 1 9 9.5A3.5 3.5 0 1 1 9 2.5ZM9 9.5V16" />
    </svg>
  );
}

export function MicGlyph({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true" {...base}>
      <path d="M6.5 3H11.5V10H6.5ZM4 8.5V10.5H5.5M14 8.5V10.5H12.5M5.5 12.5H12.5M9 12.5V15.5M6.5 15.5H11.5" />
    </svg>
  );
}
