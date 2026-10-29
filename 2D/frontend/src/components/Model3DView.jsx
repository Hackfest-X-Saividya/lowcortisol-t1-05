// "3D model" in the witness window's evidence index: the 3D face builder (the "3D MODEL" app),
// embedded full screen and opened directly on its AI face builder. Its files are served
// unchanged under /nishaan3d/ (see nishaan3d.js); this component only hides the screens that
// are not used here (landing, case setup, method choice, desktop window buttons) and switches
// the page to its editor with the AI panel open. The face builder talks to its own service on
// http://127.0.0.1:5001 (start it with `python backend/server.py` in "3D MODEL").
import { useEffect, useRef, useState } from "react";
import { InkButton, Paper } from "./Paper.jsx";
import { BackGlyph } from "./Glyph.jsx";

const SRC = "/nishaan3d/src/renderer/index.html";
const SERVICE_HEALTH = "http://127.0.0.1:5001/api/health";
const EMBED_CSS = `
#rf-screen-hero, #rf-screen-case-setup, #rf-screen-input-method { display: none !important; }
.rf-topbar-wctrl, #titlebar .titlebar-controls { display: none !important; }
`;

export default function Model3DView({ open, onClose }) {
  const frameRef = useRef(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [service, setService] = useState("checking"); // checking | up | down

  useEffect(() => {
    if (!open) return undefined;
    let stop = false;
    setService("checking");
    fetch(SERVICE_HEALTH)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(() => !stop && setService("up"))
      .catch(() => !stop && setService("down"));
    // the 3D view was hidden: let it measure its canvas again
    frameRef.current?.contentWindow?.dispatchEvent(new Event("resize"));
    return () => {
      stop = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === "Escape" && e.target === document.body && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const onLoad = () => {
    setReady(false);
    setFailed(false);
    let win;
    let doc;
    try {
      win = frameRef.current?.contentWindow;
      doc = win?.document;
    } catch {
      doc = null;
    }
    if (!win || !doc) {
      setFailed(true);
      return;
    }
    if (!doc.getElementById("nishaan-embed")) {
      const style = doc.createElement("style");
      style.id = "nishaan-embed";
      style.textContent = EMBED_CSS;
      doc.head.appendChild(style);
    }
    let tries = 0;
    const openEditor = () => {
      const router = win.rfRouter;
      if (!router) {
        if (++tries > 150) setFailed(true);
        else setTimeout(openEditor, 100);
        return;
      }
      if (router.current !== "editor") {
        // same as choosing "Text description" on the method screen: editor with the AI panel
        router.selectedMethods.clear();
        router.selectedMethods.add("text-description");
        router.navigateTo("editor");
      }
      setTimeout(() => setReady(true), (router.TRANSITION_MS || 400) * 2 + 100);
    };
    openEditor();
  };

  return (
    <div className="model3d-cover" hidden={!open} role="dialog" aria-modal="true" aria-label="3D model: AI face builder">
      <div className="model3d-bar">
        <InkButton onClick={onClose} glyph={<BackGlyph />}>
          Evidence index
        </InkButton>
        <Paper seed="model3d-head" rotate={-0.8} jag={2.4} className="model3d-title">
          <span className="ink">3D model · AI face builder</span>
        </Paper>
        {service === "down" && (
          <p className="model3d-warn" role="status">
            The 3D face service is not running. In the &quot;3D MODEL&quot; folder run <code>python backend/server.py</code>, then reopen.
          </p>
        )}
      </div>
      <div className="model3d-stage">
        <iframe
          ref={frameRef}
          className={`model3d-frame ${ready ? "is-ready" : ""}`}
          src={SRC}
          title="3D face builder"
          allow="microphone; camera; clipboard-write; fullscreen"
          onLoad={onLoad}
        />
        {!ready && (
          <p className="model3d-loading" role="status">
            {failed ? "The 3D face builder could not be opened." : "Opening the 3D face builder…"}
          </p>
        )}
      </div>
    </div>
  );
}
