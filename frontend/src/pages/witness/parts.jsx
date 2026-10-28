// Building blocks of the witness window.
import { useState } from "react";
import { Paper, Strip, InkButton } from "../../components/Paper.jsx";
import { ArrowGlyph, MicGlyph } from "../../components/Glyph.jsx";
import { useRecorder } from "../../lib/useRecorder.js";

/** Text in the witness's language (Kannada / Hindi fonts, no ink distortion). */
export function L({ lang, children, as: Tag = "span", className = "", ...rest }) {
  return (
    <Tag lang={lang} className={`wl wl-${lang} ${className}`} {...rest}>
      {children}
    </Tag>
  );
}

/** Speak (record) or type an answer in the witness's own words. */
export function WordsBox({ t, onText, onAudio, busy, placeholder, submitLabel = "Continue" }) {
  const [text, setText] = useState("");
  const rec = useRecorder();
  const toggle = async () => {
    if (rec.recording) {
      const file = await rec.stop();
      if (file && file.size > 0) onAudio(file);
    } else {
      await rec.start();
    }
  };
  return (
    <div className="words-box">
      {rec.supported && (
        <InkButton
          className={`record ${rec.recording ? "is-recording" : ""}`}
          onClick={toggle}
          disabled={busy && !rec.recording}
          glyph={<MicGlyph />}
          aria-pressed={rec.recording}
        >
          {rec.recording ? "Stop and send" : "Record"}
        </InkButton>
      )}
      {rec.recording && (
        <p className="recording-line" lang={t.lang}>
          <span className="rec-dot" aria-hidden="true" /> {t("recording")}
        </p>
      )}
      <label className="sr-only" htmlFor="words-text">
        {t("orType")}
      </label>
      <textarea
        id="words-text"
        className="paper-input words-text"
        lang={t.lang}
        placeholder={placeholder || t("orType")}
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={busy || rec.recording}
      />
      <InkButton
        variant="solid"
        onClick={() => {
          const v = text.trim();
          if (v) {
            onText(v);
            setText("");
          }
        }}
        disabled={busy || rec.recording || !text.trim()}
        glyph={<ArrowGlyph />}
      >
        {submitLabel}
      </InkButton>
    </div>
  );
}

/** Calm "one moment" note pinned over the sheet while work happens (no looping motion). */
export function WorkingNote({ t, text }) {
  return (
    <Paper seed="working" rotate={-1} className="working-note" pins={[{ id: "working-pin", x: "50%" }]}>
      <L lang={t.lang} as="p">
        {text || t("working")}
      </L>
    </Paper>
  );
}

export function HeadingStrip({ t, text, seed = "sheet-head" }) {
  return (
    <Paper seed={seed} rotate={-0.7} jag={2.4} className="sheet-heading">
      <L lang={t.lang} as="h1">
        {text}
      </L>
    </Paper>
  );
}

export function CaptionStrip({ t, text, seed = "sheet-caption" }) {
  return (
    <Paper seed={seed} rotate={0.9} jag={2.2} className="sheet-caption">
      <L lang={t.lang} as="p">
        {text}
      </L>
    </Paper>
  );
}

export { Strip };
