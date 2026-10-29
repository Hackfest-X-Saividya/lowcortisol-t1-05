// The landing page's torch for the staff wall: a soft circle of light follows the mouse and
// the rest of the wall dims. It sits behind every paper (it only dims the felt and the
// strings, never a form), ignores the pointer, and is off on touch screens and under
// prefers-reduced-motion.
import { useEffect, useMemo, useRef } from "react";

export default function Torch() {
  const ref = useRef(null);
  const on = useMemo(
    () =>
      window.matchMedia?.("(hover: hover) and (pointer: fine)").matches &&
      !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
    [],
  );

  useEffect(() => {
    if (!on) return undefined;
    let frame = 0;
    const move = (e) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const el = ref.current;
        const box = el?.parentElement?.getBoundingClientRect();
        if (!el || !box) return;
        el.style.transform = `translate3d(${e.clientX - box.left}px, ${e.clientY - box.top}px, 0)`;
        el.classList.add("lit");
      });
    };
    window.addEventListener("mousemove", move);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("mousemove", move);
    };
  }, [on]);

  if (!on) return null;
  return (
    <div className="wall-torch-clip" aria-hidden="true">
      <div ref={ref} className="wall-torch" />
    </div>
  );
}
