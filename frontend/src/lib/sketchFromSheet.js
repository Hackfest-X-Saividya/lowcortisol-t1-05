// Turns the interview's feature sheet (short English values written by the LLM, e.g.
// "long, slightly hooked") plus the witness's spoken corrections into PencilFace params,
// and decides which feature groups are drawn (the rest stay as faint construction guides).

const has = (v, ...words) => words.some((w) => v.includes(w));

function val(sheet, key) {
  const e = sheet?.[key];
  if (!e || typeof e !== "object") return "";
  const v = String(e.value ?? "").toLowerCase().trim();
  return v === "not_remembered" ? "" : v.replace(/_/g, " ");
}

const KNOWN = (sheet, key) => {
  const e = sheet?.[key];
  return !!(e && typeof e === "object" && String(e.value ?? "").trim());
};

// slider adjustments (fractions of face width from the backend) -> drawing scale
const ADJUST = {
  jaw_width: (p, a) => (p.jawW = (p.jawW ?? 1) + a * 2.4),
  face_length: (p, a) => (p.faceL = (p.faceL ?? 1) + a * 1.4),
  eye_size: (p, a) => (p.eyeSize = (p.eyeSize ?? 1) + a * 2.6),
  eye_spacing: (p, a) => (p.eyeGap = (p.eyeGap ?? 1) + a * 1.8),
  nose_length: (p, a) => (p.noseL = (p.noseL ?? 1) + a * 2.6),
  nose_width: (p, a) => (p.noseW = (p.noseW ?? 1) + a * 2.6),
  lip_fullness: (p, a) => (p.lipF = (p.lipF ?? 1) + a * 3.5),
  brow_height: (p, a) => (p.browH = (p.browH ?? 0) + a * 8),
};

export function sketchFromSheet(sheet = {}, adjust = {}) {
  const p = {};
  const reveal = new Set();

  // overall -> the head outline is drawn as soon as anything about the person is known
  const overall = ["gender", "age_range", "build", "skin_tone", "face_shape", "jaw", "height_relative"];
  if (overall.some((k) => KNOWN(sheet, k)) || Object.keys(sheet).length > 0) reveal.add("head");

  const gender = val(sheet, "gender");
  const age = val(sheet, "age_range");
  const build = val(sheet, "build");
  const skin = val(sheet, "skin_tone");
  if (has(age, "under 20", "teen", "young", "20", "twent")) p.age = "young";
  if (has(age, "40", "50", "forty", "fifty", "old", "elder", "over")) p.age = "older";
  if (p.age === "older") reveal.add("age");
  if (has(build, "thin", "slim", "lean", "skinny")) p.faceW = 0.9;
  if (has(build, "heavy", "fat", "stout", "plump", "big")) p.faceW = 1.15;
  if (has(build, "muscular", "strong", "well built")) p.jawW = 1.08;
  if (skin) p.shade = has(skin, "fair", "light", "pale") ? 0.15 : has(skin, "dark", "dusky", "black") ? 0.7 : has(skin, "wheat") ? 0.32 : 0.48;

  const face = val(sheet, "face_shape");
  if (face) {
    if (has(face, "round", "chubby")) p.shape = "round";
    else if (has(face, "square", "broad")) p.shape = "square";
    else if (has(face, "long", "oblong", "elongated")) p.shape = "long";
    else if (has(face, "heart")) p.shape = "heart";
    else if (has(face, "diamond")) p.shape = "diamond";
    else if (has(face, "narrow", "thin", "slim")) p.shape = "narrow";
    else p.shape = "oval";
  }

  const jaw = val(sheet, "jaw");
  if (jaw) {
    if (has(jaw, "wide", "broad", "strong", "heavy")) p.jawW = (p.jawW ?? 1) * 1.16;
    if (has(jaw, "narrow", "thin", "small")) p.jawW = (p.jawW ?? 1) * 0.84;
    if (has(jaw, "square")) p.chin = "square";
    else if (has(jaw, "pointed", "sharp")) p.chin = "pointed";
    else if (has(jaw, "round")) p.chin = "round";
  }

  const hair = val(sheet, "hair");
  if (hair) {
    reveal.add("hair");
    if (has(hair, "bald", "no hair", "shaved")) p.hair = "bald";
    else if (has(hair, "reced")) p.hair = "receding";
    else if (has(hair, "curl", "wavy")) p.hair = "short_curly";
    else if (has(hair, "long")) p.hair = "long";
    else if (has(hair, "medium", "shoulder")) p.hair = "medium";
    else if (has(hair, "grey", "gray", "white")) p.hair = "grey";
    else p.hair = "short";
  } else if (gender.includes("female") || gender.includes("woman")) {
    p.hair = "long";
  }

  const eyes = val(sheet, "eyes");
  if (eyes) {
    reveal.add("eyes");
    if (has(eyes, "big", "large", "wide open")) p.eyeSize = 1.25;
    if (has(eyes, "small", "tiny")) p.eyeSize = 0.8;
    if (has(eyes, "narrow", "slit", "squint")) p.eyeShape = "narrow";
    else if (has(eyes, "round")) p.eyeShape = "round";
    else if (has(eyes, "deep", "sunken")) p.eyeShape = "deep_set";
    else if (has(eyes, "hooded", "heavy lid", "droopy")) p.eyeShape = "hooded";
    if (has(eyes, "close together", "close-set", "closely")) p.eyeGap = 0.88;
    if (has(eyes, "far apart", "wide set", "wide-set")) p.eyeGap = 1.12;
  }

  const brows = val(sheet, "brows");
  if (brows) {
    reveal.add("brows");
    if (has(brows, "thick", "bushy", "heavy", "dense")) p.brow = "thick";
    else if (has(brows, "thin", "light", "sparse")) p.brow = "thin";
    if (has(brows, "arch", "curved")) p.brow = p.brow === "thick" ? "thick" : "arched";
    if (has(brows, "joined", "unibrow", "meet")) p.brow = "joined";
    if (has(brows, "straight", "flat")) p.brow = p.brow || "straight";
  }

  const nose = val(sheet, "nose");
  if (nose) {
    reveal.add("nose");
    if (has(nose, "hook", "beak", "aquiline", "parrot", "bump")) p.nose = "hooked";
    else if (has(nose, "flat")) p.nose = "flat";
    else if (has(nose, "broad", "wide", "big", "fat")) p.nose = "broad";
    else if (has(nose, "upturn", "snub", "turned up")) p.nose = "upturned";
    else if (has(nose, "small", "tiny", "short")) p.nose = "small";
    else if (has(nose, "long", "pointed", "sharp")) p.nose = "long";
    if (has(nose, "long", "pointed")) p.noseL = 1.18;
    if (has(nose, "short", "small")) p.noseL = 0.88;
    if (has(nose, "thin", "narrow", "sharp")) p.noseW = 0.85;
  }

  const mouth = val(sheet, "mouth");
  if (mouth) {
    reveal.add("mouth");
    if (has(mouth, "thin")) p.lips = "thin";
    if (has(mouth, "full", "thick", "fat", "big lips")) p.lips = "full";
    if (has(mouth, "wide", "big", "large")) p.mouthW = 1.2;
    if (has(mouth, "small", "narrow")) p.mouthW = 0.8;
  }

  const ears = val(sheet, "ears");
  if (ears) {
    if (has(ears, "big", "large")) p.ears = "large";
    if (has(ears, "stick", "protrud", "out")) p.ears = "protruding";
    if (has(ears, "small")) p.ears = "small";
  }

  const fh = val(sheet, "facial_hair");
  if (fh) {
    reveal.add("facial");
    if (has(fh, "none", "no ", "clean", "shaven", "without")) p.facial = "none";
    else if (has(fh, "full beard", "long beard", "thick beard")) p.facial = "full_beard";
    else if (has(fh, "goatee")) p.facial = "goatee";
    else if (has(fh, "stubble", "light beard", "unshaven")) p.facial = "stubble";
    else if (has(fh, "beard")) p.facial = has(fh, "moustache", "mustache") ? "full_beard" : "full_beard";
    else if (has(fh, "thick moustache", "thick mustache", "heavy moustache")) p.facial = "moustache_thick";
    else if (has(fh, "moustache", "mustache")) p.facial = "moustache";
  }

  const head = val(sheet, "headwear");
  if (head && !has(head, "none", "nothing", "no ")) {
    reveal.add("headwear");
    if (has(head, "turban", "pagdi", "pagri")) p.head = "turban";
    else if (has(head, "helmet")) p.head = "helmet";
    else if (has(head, "hood")) p.head = "hood";
    else if (has(head, "cap", "hat")) p.head = "cap";
  }

  const eyewear = val(sheet, "eyewear");
  if (eyewear && !has(eyewear, "none", "nothing", "no ")) {
    reveal.add("eyewear");
    p.eyewear = has(eyewear, "sun", "dark", "black") ? "sunglasses" : "spectacles";
  }

  const cover = val(sheet, "face_cover");
  if (cover && !has(cover, "none", "nothing", "no ")) {
    reveal.add("cover");
    p.cover = has(cover, "mask") ? "mask" : has(cover, "partial", "half") ? "partial" : "cloth";
  }

  const scars = val(sheet, "scars");
  const moles = val(sheet, "moles");
  const marks = val(sheet, "other_marks");
  if (scars && !has(scars, "none", "no ")) {
    reveal.add("marks");
    p.mark = "scar";
  } else if ((moles && !has(moles, "none", "no ")) || has(marks, "mole")) {
    reveal.add("marks");
    p.mark = "mole";
  } else if (has(marks, "scar")) {
    reveal.add("marks");
    p.mark = "scar";
  }

  // spoken corrections ("make the jaw a bit wider")
  for (const [k, a] of Object.entries(adjust || {})) ADJUST[k]?.(p, Number(a) || 0);

  // a corrected feature is clearly on the drawing
  const touched = { jaw_width: "head", face_length: "head", eye_size: "eyes", eye_spacing: "eyes", nose_length: "nose", nose_width: "nose", lip_fullness: "mouth", brow_height: "brows" };
  for (const k of Object.keys(adjust || {})) if (touched[k]) reveal.add(touched[k]);

  return { params: p, reveal: [...reveal] };
}

/** Order in which newly revealed groups are drawn, one after another. */
export const DRAW_ORDER = ["head", "hair", "brows", "eyes", "nose", "mouth", "facial", "marks", "age", "headwear", "eyewear", "cover"];
