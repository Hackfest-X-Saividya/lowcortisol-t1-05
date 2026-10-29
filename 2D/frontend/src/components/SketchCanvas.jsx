/*
  The live forensic sketch on the centre sheet.

  Each new drawing from the backend comes as two pencil layers of the same face:
    lines  - outlines only (drawn first, stroke by stroke, top to bottom)
    shade  - the full graphite composite (filled in over the outlines)
  The previous drawing fades back like erased graphite while the new one is drawn over it.
  Images are multiplied onto the manila paper so the white of the sketch is the paper itself.
*/
import { useEffect, useRef, useState } from "react";

export default function SketchCanvas({ frame, className = "", onShown }) {
  const [cur, setCur] = useState(null);
  const [prev, setPrev] = useState(null);
  const curRef = useRef(null);
  // the last drawing whose shading finished appearing: it stays under a new drawing until that
  // one is complete, so quick successive updates never leave the sheet empty
  const shownRef = useRef(null);

  useEffect(() => {
    if (!frame || frame.id === curRef.current?.id) return;
    setPrev(shownRef.current);
    curRef.current = frame;
    setCur(frame);
  }, [frame]);

  return (
    <div className={`sketch-canvas ${className}`} aria-live="polite">
      {prev && <img key={`p-${prev.id}`} className="sc-layer sc-prev" src={prev.shade} alt="" aria-hidden="true" />}
      {cur && (
        <>
          <img key={`l-${cur.id}`} className={`sc-layer sc-lines ${prev ? "" : "first"}`} src={cur.lines} alt="" aria-hidden="true" />
          <img
            key={`s-${cur.id}`}
            className={`sc-layer sc-shade ${prev ? "" : "first"}`}
            src={cur.shade}
            alt="Pencil sketch of the person, as described so far"
            onAnimationEnd={() => {
              shownRef.current = cur;
              setPrev(null);
              onShown?.(cur);
            }}
          />
        </>
      )}
    </div>
  );
}
