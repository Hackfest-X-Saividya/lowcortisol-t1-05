// Voice for the live interview.
//
// Listening works the same in every browser: the microphone is recorded (MediaRecorder) and a
// level meter (WebAudio) notices when the witness starts and stops talking. While they talk,
// the audio so far is sent to the backend every couple of seconds (Groq Whisper, about 1 s),
// so their words appear on screen as they speak. A pause of about 1.7 s ends the answer (or the
// "I have finished speaking" button); the recording is then sent as the turn.
// The browser Web Speech API is not used: most browsers have no Kannada for it and it fails
// silently.
//
// Speaking: a browser voice for the language if one exists, otherwise audio from the
// backend /tts endpoint (Gemini speech), otherwise text only. If the backend voice takes too
// long, the question stays on screen and listening starts anyway.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";

const LOCALE = { kn: "kn-IN", hi: "hi-IN", en: "en-IN" };
const END_SILENCE_MS = 1700;
const NO_SPEECH_MS = 15000;
const MAX_MS = 45000;
const INTERIM_EVERY_MS = 2000;
const TTS_WAIT_MS = 5000;

function pickMime() {
  if (typeof MediaRecorder === "undefined") return "";
  for (const m of ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/ogg", "audio/mp4"]) {
    if (MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

/**
 * useListener(lang, { sid, token })
 * listen() resolves with { audio: File, text: words so far } or { audio: null } when nothing
 * was said (or { audio: null, cancelled: true }).
 */
export function useListener(lang, { sid, token } = {}) {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [level, setLevel] = useState(0);
  const [heardVoice, setHeardVoice] = useState(false);
  const [error, setError] = useState(null);
  const run = useRef(null);
  const streamRef = useRef(null);

  const supported = typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";

  const getStream = useCallback(async () => {
    const live = streamRef.current?.getAudioTracks?.().some((t) => t.readyState === "live");
    if (live) return streamRef.current;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    streamRef.current = stream;
    return stream;
  }, []);

  const end = useCallback((reason) => {
    const r = run.current;
    if (!r || r.ending) return;
    r.ending = reason;
    try {
      if (r.rec.state !== "inactive") r.rec.stop();
      else r.finish();
    } catch {
      r.finish();
    }
  }, []);

  const listen = useCallback(
    () =>
      new Promise((resolve) => {
        if (run.current) end("cancel"); // never two recordings at once
        setError(null);
        setInterim("");
        setLevel(0);
        setHeardVoice(false);
        if (!supported) {
          setError("unavailable");
          resolve({ audio: null });
          return;
        }
        getStream()
          .then((stream) => {
            const mime = pickMime();
            const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
            const type = (rec.mimeType || mime || "audio/webm").split(";")[0];
            const ext = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "m4a" : "webm";
            const chunks = [];
            const Ctx = window.AudioContext || window.webkitAudioContext;
            const ctx = new Ctx();
            ctx.resume?.().catch(() => {});
            const src = ctx.createMediaStreamSource(stream);
            const an = ctx.createAnalyser();
            an.fftSize = 1024;
            src.connect(an);
            const buf = new Float32Array(an.fftSize);
            const t0 = performance.now();
            const r = {
              rec,
              ending: null,
              spoke: false,
              voiceMs: 0,
              lastVoice: 0,
              floor: 0.003,
              lastInterimAt: 0,
              interimBusy: false,
              interimText: "",
              timer: 0,
              finished: false,
              finish: null,
            };
            run.current = r;

            const file = () => new File([new Blob(chunks, { type })], `answer.${ext}`, { type });

            const askInterim = async () => {
              if (!sid || r.interimBusy || r.ending || chunks.length === 0) return;
              r.interimBusy = true;
              r.lastInterimAt = performance.now();
              try {
                const fd = new FormData();
                fd.append("audio", file());
                fd.append("language", lang);
                const res = await api(`/sessions/${sid}/transcribe`, { method: "POST", form: fd, token });
                const text = (res?.text || "").trim();
                if (text && run.current === r) {
                  r.interimText = text;
                  setInterim(text);
                }
              } catch {
                /* the final answer is still sent as audio */
              } finally {
                r.interimBusy = false;
              }
            };

            // setInterval, not requestAnimationFrame: keeps working in a background tab
            let prev = t0;
            const tick = () => {
              if (run.current !== r || r.ending) return;
              const now = performance.now();
              const dt = now - prev;
              prev = now;
              an.getFloatTimeDomainData(buf);
              let sum = 0;
              for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
              const rms = Math.sqrt(sum / buf.length);
              const elapsed = now - t0;
              if (elapsed < 300) r.floor = Math.max(r.floor, Math.min(rms, 0.03)); // room noise
              const threshold = Math.max(0.01, r.floor * 2.2);
              if (rms > threshold) {
                r.voiceMs += dt;
                r.lastVoice = now;
                if (!r.spoke && r.voiceMs > 160) {
                  r.spoke = true;
                  setHeardVoice(true);
                }
              }
              setLevel(Math.min(1, rms / 0.1));
              if (r.spoke && now - r.lastInterimAt > INTERIM_EVERY_MS) askInterim();
              if (r.spoke && now - r.lastVoice > END_SILENCE_MS) end("silence");
              else if (!r.spoke && elapsed > NO_SPEECH_MS) end("no_speech");
              else if (elapsed > MAX_MS) end("max");
            };

            r.finish = () => {
              if (r.finished) return;
              r.finished = true;
              clearInterval(r.timer);
              try {
                src.disconnect();
              } catch {
                /* ignore */
              }
              ctx.close().catch(() => {});
              if (run.current === r) run.current = null;
              setListening(false);
              setLevel(0);
              const cancelled = r.ending === "cancel";
              const said = r.spoke || (r.ending === "button" && r.voiceMs > 0);
              resolve(cancelled || !said || chunks.length === 0 ? { audio: null, cancelled } : { audio: file(), text: r.interimText });
            };
            rec.ondataavailable = (e) => {
              if (e.data && e.data.size) chunks.push(e.data);
            };
            rec.onstop = () => r.finish();
            rec.start(400);
            setListening(true);
            r.timer = setInterval(tick, 50);
          })
          .catch((e) => {
            setError(e?.name === "NotAllowedError" || e?.name === "SecurityError" ? "denied" : "unavailable");
            resolve({ audio: null });
          });
      }),
    [supported, getStream, end, lang, sid, token],
  );

  /** "I have finished speaking": end now and keep what was said. */
  const stop = useCallback(() => end("button"), [end]);
  const cancel = useCallback(() => end("cancel"), [end]);

  useEffect(
    () => () => {
      end("cancel");
      streamRef.current?.getTracks().forEach((t) => t.stop());
    },
    [end],
  );

  return { listening, interim, level, heardVoice, error, supported, listen, stop, cancel };
}

// ---- speaking ----------------------------------------------------------------------------

function pickVoice(lang) {
  const voices = window.speechSynthesis?.getVoices?.() || [];
  const loc = LOCALE[lang] || "en-IN";
  return voices.find((v) => v.lang === loc) || voices.find((v) => v.lang?.toLowerCase().startsWith(lang)) || null;
}

const audioCache = new Map();

export function useSpeaker(token) {
  const [speaking, setSpeaking] = useState(false);
  const current = useRef(null);
  const ticket = useRef(0);
  const [, force] = useState(0);

  useEffect(() => {
    const s = window.speechSynthesis;
    if (!s) return undefined;
    const on = () => force((n) => n + 1);
    s.addEventListener?.("voiceschanged", on);
    return () => s.removeEventListener?.("voiceschanged", on);
  }, []);

  const stopSpeaking = useCallback(() => {
    ticket.current += 1;
    window.speechSynthesis?.cancel();
    if (current.current) {
      current.current.pause();
      current.current = null;
    }
    setSpeaking(false);
  }, []);

  /** Fetch (and cache) the backend voice for a line; null when there is none. */
  const fetchAudio = useCallback(
    async (text, lang) => {
      const key = `${lang}:${text}`;
      if (audioCache.has(key)) return audioCache.get(key);
      const p = api("/tts", { method: "POST", body: { text, language: lang }, token, raw: true })
        .then(async (r) => (r.status === 200 ? URL.createObjectURL(await r.blob()) : null))
        .catch(() => null);
      audioCache.set(key, p);
      const url = await p;
      if (!url) audioCache.delete(key);
      return url;
    },
    [token],
  );

  /** Speak a line; resolves when finished (or soon if no voice is available). */
  const speak = useCallback(
    async (text, lang, { muted = false } = {}) => {
      stopSpeaking();
      if (!text || muted) return;
      const mine = ticket.current;
      const voice = pickVoice(lang);
      if (voice && window.speechSynthesis) {
        await new Promise((resolve) => {
          const u = new SpeechSynthesisUtterance(text);
          u.voice = voice;
          u.lang = voice.lang;
          u.rate = 0.95;
          u.onend = resolve;
          u.onerror = resolve;
          setSpeaking(true);
          window.speechSynthesis.speak(u);
        });
        setSpeaking(false);
        return;
      }
      try {
        const url = await Promise.race([fetchAudio(text, lang), new Promise((r) => setTimeout(() => r(null), TTS_WAIT_MS))]);
        if (!url || ticket.current !== mine) return;
        await new Promise((resolve) => {
          const a = new Audio(url);
          current.current = a;
          a.onended = resolve;
          a.onerror = resolve;
          a.onpause = resolve;
          setSpeaking(true);
          a.play().catch(resolve);
        });
      } finally {
        if (ticket.current === mine) {
          current.current = null;
          setSpeaking(false);
        }
      }
    },
    [stopSpeaking, fetchAudio],
  );

  useEffect(() => stopSpeaking, [stopSpeaking]);
  return { speaking, speak, stopSpeaking, prefetch: fetchAudio };
}
