// SketchAnnotator — wraps any sketch image with click-to-pin annotation mode.
//
// Props:
//   children   — the sketch image / canvas element
//   active     — boolean; when true clicks place pins
//   pins       — array of { id, x, y, note } (x/y in 0–1 normalised to image)
//   onAdd      — (pin) => void   called when a pin is committed
//   onRemove   — (id)  => void
//   onClear    — ()    => void

import { useRef, useState, useCallback } from "react";
import { CrossGlyph } from "./Glyph.jsx";

let _nextId = 1;

export default function SketchAnnotator({ children, active, pins = [], onAdd, onRemove, onClear }) {
  const wrapRef = useRef(null);
  const [draft, setDraft] = useState(null); // {x, y} normalised pending pin
  const [note, setNote] = useState("");

  const handleClick = useCallback(
    (e) => {
      if (!active) return;
      const rect = wrapRef.current.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;
      setDraft({ x, y });
      setNote("");
    },
    [active]
  );

  const commitPin = () => {
    if (!draft || !note.trim()) return;
    onAdd?.({ id: `pin-${_nextId++}`, x: draft.x, y: draft.y, note: note.trim() });
    setDraft(null);
    setNote("");
  };

  const cancelDraft = () => {
    setDraft(null);
    setNote("");
  };

  return (
    <div className="sketch-annotator" ref={wrapRef} onClick={handleClick}>
      {/* The sketch itself */}
      {children}

      {/* Committed pins */}
      {pins.map((p) => (
        <div
          key={p.id}
          className="annot-pin committed"
          style={{ left: `${p.x * 100}%`, top: `${p.y * 100}%` }}
          title={p.note}
          onClick={(e) => {
            e.stopPropagation();
            onRemove?.(p.id);
          }}
        >
          <span className="annot-pin-dot" />
          <div className="annot-bubble">{p.note}</div>
        </div>
      ))}

      {/* Draft pin (not yet committed) */}
      {draft && (
        <div
          className="annot-pin draft"
          style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%` }}
          onClick={(e) => e.stopPropagation()}
        >
          <span className="annot-pin-dot" />
          <div className="annot-bubble annot-input-bubble">
            <textarea
              className="annot-textarea"
              rows={2}
              autoFocus
              placeholder="What should change here?"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  commitPin();
                }
                if (e.key === "Escape") cancelDraft();
              }}
            />
            <div className="annot-btn-row">
              <button className="annot-btn annot-ok" onClick={commitPin} disabled={!note.trim()}>
                Add
              </button>
              <button className="annot-btn annot-cancel" onClick={cancelDraft} aria-label="Cancel">
                <CrossGlyph size={14} />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Clear all button */}
      {pins.length > 0 && !active && (
        <button className="annot-clear-btn" onClick={(e) => { e.stopPropagation(); onClear?.(); }}>
          Clear notes
        </button>
      )}
    </div>
  );
}

/** Convert an array of pins into a plain-English prefix for the turn text. */
export function pinsToText(pins) {
  if (!pins.length) return "";
  return pins
    .map((p, i) => `[Point ${i + 1} at ${Math.round(p.x * 100)}%,${Math.round(p.y * 100)}% of face: ${p.note}]`)
    .join(" ");
}
