// Microphone recording with MediaRecorder (webm/ogg). No looping animation is shown while
// recording; the UI uses a static red state instead.
import { useCallback, useEffect, useRef, useState } from "react";

export function useRecorder() {
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState(null);
  const rec = useRef(null);
  const chunks = useRef([]);
  const resolver = useRef(null);

  const supported = typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";

  const start = useCallback(async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : MediaRecorder.isTypeSupported("audio/ogg") ? "audio/ogg" : "";
      const r = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunks.current = [];
      r.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      r.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const type = r.mimeType || mime || "audio/webm";
        const blob = new Blob(chunks.current, { type });
        resolver.current?.(new File([blob], type.includes("ogg") ? "statement.ogg" : "statement.webm", { type }));
        resolver.current = null;
        rec.current = null;
        setRecording(false);
      };
      rec.current = r;
      r.start();
      setRecording(true);
    } catch (e) {
      setError(e?.name === "NotAllowedError" ? "denied" : "unavailable");
    }
  }, []);

  /** Stop and resolve with the recorded File. */
  const stop = useCallback(
    () =>
      new Promise((resolve) => {
        if (!rec.current) return resolve(null);
        resolver.current = resolve;
        rec.current.stop();
        return undefined;
      }),
    [],
  );

  useEffect(
    () => () => {
      if (rec.current?.state === "recording") rec.current.stop();
    },
    [],
  );

  return { supported, recording, error, start, stop };
}
