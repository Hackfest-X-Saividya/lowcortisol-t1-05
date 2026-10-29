"""
Nishaan — Python Backend Server
Handles Blender engine integration, mesh operations, 3D export, and AI face generation.
Uses Flask API to communicate with the Electron/Three.js frontend.
"""

import os
import sys
import json
import re
import uuid
import base64
import subprocess
import tempfile
from pathlib import Path

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv
from groq import Groq, RateLimitError, APIStatusError
from google import genai
from google.genai import types as genai_types
import speech_recognition as sr

# Load .env from project root, then from the repository root (shared with the 2D app).
# Values already set are kept, so a project-level .env wins.
load_dotenv(Path(__file__).parent.parent / '.env')
load_dotenv(Path(__file__).parent.parent.parent / '.env')

# Windows consoles and pipes default to cp1252, which can't print the ✓/✗ status marks
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8', errors='replace')

app = Flask(__name__)
CORS(app)

# ─── AI Clients (Groq & Gemini) ──────────────────────────────────────────────
groq_client = None
gemini_client = None

# Initialize Groq client if API key exists
groq_key = os.getenv('GROQ_API_KEY')
if groq_key:
    try:
        groq_client = Groq(api_key=groq_key)
    except Exception as e:
        print(f"Warning: Failed to initialize Groq client: {e}")

# Initialize Gemini client if API key exists
gemini_key = os.getenv('GEMINI_API_KEY')
if gemini_key:
    try:
        gemini_client = genai.Client(api_key=gemini_key)
    except Exception as e:
        print(f"Warning: Failed to initialize Gemini client: {e}")
        gemini_client = None

# Default AI provider (can be overridden per request)
DEFAULT_AI_PROVIDER = os.getenv('AI_PROVIDER', 'groq')  # 'groq' or 'gemini'

# Models used when the request doesn't specify one
DEFAULT_GROQ_MODEL = os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b')
# Swapped in whenever reference images are attached — the text model can't see them.
DEFAULT_GROQ_VISION_MODEL = os.getenv('GROQ_VISION_MODEL', 'qwen/qwen3.8-27b')
GROQ_VISION_MODELS = {DEFAULT_GROQ_VISION_MODEL, 'qwen/qwen3.8-27b'}
GROQ_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    'GROQ_FALLBACK_MODELS', 'qwen/qwen3.8-27b,openai/gpt-oss-20b').split(',') if m.strip()]
DEFAULT_GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-flash-latest')
GROQ_WHISPER_MODEL = os.getenv('GROQ_WHISPER_MODEL', 'whisper-large-v3-turbo')

AI_PROVIDERS = ('groq', 'gemini')


def _provider_error(provider):
    """Return an error response if the provider is unknown or has no key, else None."""
    if provider == 'groq' and not groq_client:
        return jsonify({"error": "Groq API key not set in .env file (GROQ_API_KEY)"}), 500
    if provider == 'gemini' and not gemini_client:
        return jsonify({"error": "Gemini API key not set in .env file (GEMINI_API_KEY)"}), 500
    if provider not in AI_PROVIDERS:
        return jsonify({"error": f"Invalid provider '{provider}'. Use 'groq' or 'gemini'"}), 400
    return None


def _history_text(content):
    """Flatten a history message to plain text (image blocks are dropped to save tokens)."""
    if isinstance(content, list):
        return '\n'.join(
            block.get('text', '') for block in content
            if isinstance(block, dict) and block.get('type') == 'text'
        )
    return content or ''


def _groq_complete(system_prompt, history, user_content, image_payloads, model, max_tokens):
    """Run one JSON-mode chat completion on Groq and return the raw text."""
    messages = [{"role": "system", "content": system_prompt}]
    # Keep requests small (free-tier models allow ~7k input tokens/minute): the
    # current face state already reflects earlier AI replies, so only the
    # user's recent instructions are sent as history.
    user_turns = [_history_text(m.get('content')) for m in (history or []) if m.get('role') == 'user']
    for text in [t for t in user_turns if t][-3:]:
        messages.append({"role": "user", "content": text[:600]})
        messages.append({"role": "assistant", "content": "{}"})

    if image_payloads:
        if model not in GROQ_VISION_MODELS:
            model = DEFAULT_GROQ_VISION_MODEL
        content = [{"type": "text", "text": user_content}]
        content.extend(
            {"type": "image_url", "image_url": {"url": f"data:{p['mime_type']};base64,{p['base64_data']}"}}
            for p in image_payloads
        )
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": user_content})

    def create(candidate, json_mode):
        extra = {"response_format": {"type": "json_object"}} if json_mode else {}
        if 'gpt-oss' in candidate:
            # Default reasoning can use the whole token budget before any JSON is written,
            # which Groq reports as json_validate_failed with an empty failed_generation.
            extra["reasoning_effort"] = "low"
        response = groq_client.chat.completions.create(
            model=candidate,
            messages=messages,
            max_completion_tokens=max_tokens,
            **extra,
        )
        text = response.choices[0].message.content or ''
        # Reasoning models can prefix the answer with a <think> block.
        return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    # Groq rate limits are per model, so on a 429 fall back to the other models.
    # A model that fails JSON validation is also skipped for the next one.
    candidates = [model or DEFAULT_GROQ_MODEL] + [m for m in GROQ_FALLBACK_MODELS if m != (model or DEFAULT_GROQ_MODEL)]
    if image_payloads:
        candidates = [m for m in candidates if m in GROQ_VISION_MODELS] or [DEFAULT_GROQ_VISION_MODEL]
    last_error = None
    json_failed = []
    for candidate in candidates:
        try:
            return create(candidate, json_mode=True)
        except (RateLimitError, APIStatusError) as e:
            status = getattr(e, 'status_code', None)
            if status in (413, 429):
                print(f"[AI] Groq model {candidate} rate-limited, trying the next model: {e}")
            elif status == 400 and 'json_validate_failed' in str(e):
                print(f"[AI] Groq model {candidate} returned invalid JSON, trying the next model")
                json_failed.append(candidate)
            else:
                raise
            last_error = e

    # JSON mode failed on every model that answered: ask once more without it and cut
    # the JSON object out of the reply.
    for candidate in json_failed:
        try:
            text = create(candidate, json_mode=False)
        except (RateLimitError, APIStatusError) as e:
            last_error = e
            continue
        start, end = text.find('{'), text.rfind('}')
        if start != -1 and end > start:
            return text[start:end + 1]
    raise last_error


def _gemini_complete(system_prompt, history, user_content, image_payloads, model):
    """Run one JSON-mode generation on Gemini and return the raw text."""
    prompt = ''
    if history:
        prompt += "Previous conversation:\n"
        for msg in history:
            role_name = "User" if msg['role'] == 'user' else "Assistant"
            prompt += f"{role_name}: {_history_text(msg.get('content'))}\n"
        prompt += "\n"
    prompt += f"User: {user_content}"

    contents = [prompt]
    contents.extend(
        genai_types.Part.from_bytes(data=p["raw_bytes"], mime_type=p["mime_type"])
        for p in image_payloads
    )
    response = gemini_client.models.generate_content(
        model=model or DEFAULT_GEMINI_MODEL,
        contents=contents,
        config=genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type='application/json',
        ),
    )
    return (response.text or '').strip()

AI_SYSTEM_PROMPT = """You are the AI face builder for Nishaan, a forensic 3D facial reconstruction tool.
Your job is to translate natural language face descriptions into precise parameter values.

You control these parameter categories:

## PERSON — put these keys INSIDE "morphTargets" (they shape the WHOLE face realistically and pick a
## matching photo skin). For a NEW face description include all seven. When refining a face that
## already exists, include only the ones the latest request actually changes.
age: integer age in YEARS, 18-90 (default 25). Use the midpoint of any stated range ("in his 40s" -> 45, "elderly" -> 75, "teenager" -> 18).
sex: 0 = female, 100 = male (use 0 or 100 unless the description is ambiguous).
ancestryAfrican, ancestryAsian, ancestryCaucasian: ancestry MIX weights 0-100 (normalised automatically; default 33/33/33).
  Guide: Black/African -> 90/5/5; East Asian (Chinese, Japanese, Korean) -> 5/90/5; White/European -> 5/5/90;
  South Asian (Indian, Pakistani, Bangladeshi) -> 20/15/65; Middle Eastern/North African -> 10/5/85;
  Hispanic/Latino -> 15/25/60; Southeast Asian (Filipino, Thai, Vietnamese) -> 10/75/15; mixed -> blend.
bodyWeight: 0 = very thin/gaunt, 50 = average, 100 = obese (affects face fullness).
muscle: 0 = frail, 50 = average, 100 = very muscular/athletic.

## MORPH TARGETS (face shape) — all integer values 0-100, where 50 = neutral/default
These are realistic anatomical shapes applied ON TOP of the person above; only change features the
description actually mentions (leave the rest out or at 50) so the face stays natural.
Skull: faceWidth, faceLength, headWidth, headLength, faceTaper (0 = square jaw-heavy face, 100 = V-shaped/heart face)
Forehead: foreheadHeight, foreheadSlope, foreheadWidth, templeWidth, foreheadBulge
Brows: browHeight, browSpacing, browProminence, browArch, browThickness
Eyes: eyeSpacing, eyeHeight, eyeDepth (100 = deep-set), eyeSize, eyeTilt, eyeOpenness (0 = narrow/hooded, 100 = wide open),
  eyeBags (100 = heavy under-eye bags), epicanthicFold (100 = pronounced epicanthic/monolid fold)
Nose: noseLength, noseWidth, noseBridgeWidth, noseBridgeHeight (100 = prominent hump), noseTipHeight (100 = upturned), noseTipWidth, nostrilFlare,
  noseCurve (0 = scooped/concave profile, 100 = hooked/aquiline)
  ⚠ Nose width parameters (noseWidth, noseBridgeWidth, noseTipWidth, nostrilFlare) are HIGH SENSITIVITY — small value changes produce large visible effects. Use conservative values closer to 50. For "slightly wide" use 55-58, "wide" use 60-65, "slightly narrow" use 42-45, "narrow" use 38-40. Avoid extreme values unless explicitly requested.
Cheeks: cheekFullness, cheekboneProminence, cheekHeight, nasolabialDepth
Mouth: mouthWidth, mouthHeight, lipProtrusion, upperLipThickness, lowerLipThickness, cupidBow, philtrumDepth, philtrumWidth, lipCornerAngle
Jaw/Chin: jawWidth, chinHeight, chinWidth, chinProtrusion, jawDefinition,
  chinCleft (0 = none, 100 = deep cleft chin; default 0), doubleChin (100 = pronounced double chin)
Ears: earSize, earProtrusion, earHeight, earlobeSize

Value guide for morphs:
- 0 = minimum (e.g., very narrow, very small, very short)
- 50 = neutral/average
- 100 = maximum (e.g., very wide, very large, very long)
- "slightly wide" ≈ 60-65, "wide" ≈ 70-75, "very wide" ≈ 80-90
- "slightly narrow" ≈ 35-40, "narrow" ≈ 25-30, "very narrow" ≈ 10-20

## HAIR — style is a string, properties are 0-100
Available styles (pick the closest match to the description):
- "hair1": Short neat crop with a soft fringe (default, typical male short hair)
- "hair2": Very short crew cut / buzz cut
- "hair3": Short with a long side-swept fringe falling over one eye
- "hair4": Short, combed/slicked back
- "hair5": Short messy, tousled
- "hair6": Short side-parted, rounded
- "hair7": Afro (medium, rounded)
- "hair8": Afro puffs (two high buns)
- "hair9": Cornrows / braided rows
- "hair10": Short spiky, textured
- "hair11": Chin-length bob with side bangs
- "hair12": Long straight hair past the shoulders
- "hair13": Hair pulled back into a ponytail
- "hair14": Long hair with side-swept bangs
- "bald": No hair (also use for a shaved head)

Hair properties (0-100): length, density, volume, curl
Hair color: hex color string (e.g., "#1a1a1a" for black, "#d4a23f" for blonde)

Curly, wavy or frizzy hair: the "curl" number alone does NOT make hair curly, so always pick a
style whose hair is curly:
- curly, tightly curled, coily, kinky, afro-textured or frizzy hair (short or medium) -> "hair7"
- big, voluminous curls of any length -> "hair7"
- loose curls, wavy or messy curly hair that is short -> "hair5"
- long curly or long wavy hair that hangs down past the shoulders -> "hair14"
- curls tied up in two puffs -> "hair8"; braided curls / cornrows -> "hair9"
Also set curl: 80-100 for curly, 50-70 for wavy, 0 for straight.

## EYEBROWS — all 0-100
Properties: thickness, arch, spacing, density

## BEARD
Style (pick the closest):
- "none": clean-shaven
- "beard1": full beard with moustache (medium length)
- "beard2": scruffy, curly full beard
- "beard3": long, bushy beard
- "beard4": short boxed beard with moustache (also use for "stubble" or "goatee and moustache")
- "beard5": small chin tuft / soul patch (use for a goatee without moustache)
- "beard6": full, trimmed beard with moustache
- "moustache1": moustache only
Color: hex color string

## APPEARANCE
skinColor: OPTIONAL hex color — OMIT it normally: a photographic skin matching age/sex/ancestry is used automatically.
  Only include it when the witness states a skin tone that differs from what the ancestry implies
  (e.g. "very pale", "deeply tanned", "sunburnt"); e.g. "#f5deb3" very light, "#d4a574" medium, "#3b2010" very dark.
lipColor: hex color string or null (e.g., "#c44569" rose, "#b33939" red, "#e08283" pink, "#cc8e7a" nude). Only set if the user mentions lip color/lipstick.
eyeColor: hex color string (e.g., "#634e34" brown, "#2e536f" blue, "#3d671d" green)
ageRange: "18-25", "25-35", "35-45", "45-55", "55-65", "65+"
sex: "male" or "female"

## FACIAL MARKS (scars, birthmarks, moles, pimples, wounds) — OPTIONAL
Include whenever the description mentions a mark on the face, in any words: mole, beauty spot,
birthmark, birth mark, port-wine stain, patch, scar, cut, stitches, wound, bruise, burn mark,
pimple, acne, spot, wart. Also include marks clearly visible in reference images.
- mole / beauty spot / wart -> "mole" (size 0.01-0.02)
- birthmark / port-wine stain / coloured patch -> "birthmark" (size 0.03-0.08)
- scar / cut / stitches / burn mark -> "scar" (size 0.02-0.06); wound / bruise -> "wound"
- pimple / acne -> "pimple" (size 0.01-0.02; several marks for acne)
- Place it where the description says ("left cheek" -> region "cheek", side "left"; "above the
  right eyebrow" -> region "brow", side "right", offset_y 0.6; "on the chin" -> region "chin",
  side "center"). Left and right are the person's own sides. If no place is given, use "cheek".
- type: "scar", "birthmark", "mole", "pimple", or "wound"
- region: "cheek", "nose", "chin", "temple", "forehead", "jaw", "mouth", "ear", "eye", "brow", "bridge"
- side: "left", "right", or "center"
- offset_x: normalized X position within region (-1 to 1, where 0 = center)
- offset_y: normalized Y position within region (-1 to 1, where 0 = center)
- size: mark size (0.01-0.1 scale)

Example facial marks:
```json
"facialMarks": [
  {"type": "scar", "region": "cheek", "side": "right", "offset_x": 0.2, "offset_y": -0.1, "size": 0.03},
  {"type": "birthmark", "region": "temple", "side": "left", "offset_x": -0.15, "offset_y": 0.05, "size": 0.02}
]
```

## GLASSES / SPECTACLES — OPTIONAL
Include this block only when the face description mentions glasses, spectacles, reading glasses, sunglasses, eyewear, or similar.
- enabled: true to show glasses on the face, false or omit for no glasses
- frameColor: hex color for the frame (e.g., "#1a1a1a" black, "#8b4513" tortoiseshell, "#c0c0c0" silver)
- lensColor: hex color for the lens tint (e.g., "#88ccff" light blue, "#333333" dark sunglasses, "#ffffff" clear)
- lensOpacity: 0–100 (0 = fully clear/no tint, 20 = light tint, 60 = medium sunglasses, 100 = fully opaque)

Example glasses:
```json
"glasses": {
  "enabled": true,
  "frameColor": "#1a1a1a",
  "lensColor": "#88ccff",
  "lensOpacity": 20
}
```

Color hints:
- Reading glasses / clear lenses: lensOpacity 0–10, lensColor "#ffffff"
- Light-tinted prescription: lensOpacity 10–25, lensColor "#88ccff" or "#e8d4a2"
- Aviator sunglasses: lensOpacity 50–70, lensColor "#333333" or "#2c4a1d"
- Dark sunglasses: lensOpacity 70–100, lensColor "#1a1a1a"
- Wire frames: frameColor "#c0c0c0" or "#d4af37"
- Thick plastic frames: frameColor "#1a1a1a" or "#8b4513"
- If the user says "no glasses" or "remove glasses", set enabled: false

## FACE MASK — OPTIONAL
Include this block only when the description mentions a face mask, surgical mask, medical mask, cloth mask, or covering the mouth and nose with a mask.
- enabled: true to show the mask, false to remove it
- style: "mask1" (cloth mask) or "mask2" (medical / surgical mask)
- maskColor: hex color of the mask body
- strapColor: hex color of the ear loops
- opacity: 0-100 (100 = solid)

Example face mask:
```json
"faceMask": {
  "enabled": true,
  "style": "mask2",
  "maskColor": "#7fb5d4",
  "strapColor": "#e6e6e6",
  "opacity": 100
}
```

Hints:
- Surgical / medical / disposable mask: style "mask2", maskColor "#7fb5d4" (blue) or "#ffffff"
- Cloth / fabric / fashion mask: style "mask1", maskColor to match the description
- Black mask: style "mask1", maskColor "#1c1c1e"

## EARRINGS — OPTIONAL
Include this block only when the description mentions earrings, studs, hoops, or a pierced ear.
- enabled: true to show earrings, false to remove them
- style: "hoop", "stud", or "drop"
- sideMode: "both", "left", or "right" — which ear. Left and right are the subject's own sides. A single piercing is common, so use "left" or "right" when the description says one ear.
- metalColor: hex color of the metal
- polish: 0-100 (0 = matte/brushed, 100 = mirror)

Example earrings:
```json
"earrings": {
  "enabled": true,
  "style": "hoop",
  "sideMode": "left",
  "metalColor": "#d4af37",
  "polish": 82
}
```

Metal hints:
- Gold: "#d4af37"   Silver: "#c8cdd2"   Rose gold: "#b76e79"   Black / gunmetal: "#3a3d42"

## BANDANA — OPTIONAL
Include this block only when the description mentions a bandana, kerchief, or a cloth pulled up over the lower face outlaw-style.
- enabled: true to show the bandana, false to remove it
- style: "paisley" (the only style available)
- tint: hex color multiplied over the printed cloth. The print is red by default, so use "#ffffff" to keep it red and a colour only to dye it.
- opacity: 0-100 (100 = solid)

Example bandana:
```json
"bandana": {
  "enabled": true,
  "style": "paisley",
  "tint": "#ffffff",
  "opacity": 100
}
```

Tint hints:
- Red bandana (the default print): tint "#ffffff"
- Blue: "#5f7fc4"   Green: "#6fae72"   Black: "#5d5d5d"

## RULES
1. ONLY output a valid JSON object. No explanations, no markdown, no comments.
2. Only include parameters you want to change. Omit parameters that should stay at default (50) or unchanged.
3. For refinement requests, you will receive the current parameter state. Apply RELATIVE changes based on the user's feedback.
4. Use the exact JSON structure shown below.
5. For "a bit" / "slightly" changes, adjust by 5-10 from current value. For "more" / "much more", adjust by 15-25.
6. If one or more reference images are attached, infer visible facial traits from them and combine that with user text instructions.
7. Include "facialMarks" whenever the description or request mentions a mark (see FACIAL MARKS), or when reference images show visible marks. When refining, list ONLY the new marks the latest request asks for: marks already on the face stay automatically, never repeat them.
8. Only include "glasses" if the description mentions glasses, spectacles, eyewear, sunglasses, or similar. If the user says "remove glasses", set enabled: false.
9. The same applies to "faceMask", "earrings" and "bandana": include each block ONLY when the description mentions that item, and set enabled: false when the user asks to remove it. Omit the block entirely otherwise.
10. A bandana and a face mask both cover the lower face, so never enable both at once. Pick whichever the description actually calls for.
11. Accessories are worn items, not facial features. Never invent them — a face described without eyewear or jewellery should return none of these blocks.
12. NEVER change anything the request does not ask for. When a current face state is given, output
    ONLY the keys the latest request changes and leave every other block and key out: do not
    repeat hair, eyebrows, beard, appearance, eye colour or the person keys, and do not "tidy up"
    other sliders. A key you leave out keeps its current value.
13. For a new description set only what it states or clearly implies. Leave undescribed features out
    (they stay natural), and never set eyeColor, lipColor or skinColor unless they are described.
14. The OUTPUT FORMAT below lists every possible block; include only the blocks you need.

## OUTPUT FORMAT (strict JSON, nothing else):
{
  "morphTargets": { "age": 40, "sex": 100, "ancestryAfrican": 5, "ancestryAsian": 5, "ancestryCaucasian": 90, "bodyWeight": 50, "muscle": 50, "paramName": value, ... },
  "hair": { "style": "hair1", "color": "#hex", "length": 50, "density": 50, "volume": 50, "curl": 0 },
  "eyebrows": { "thickness": 50, "arch": 50, "spacing": 50, "density": 70 },
  "beard": { "style": "none", "color": "#hex" },
  "appearance": { "eyeColor": "#hex", "lipColor": "#hex", "ageRange": "25-35", "sex": "male" },
  "facialMarks": [
    { "type": "scar", "region": "cheek", "side": "right", "offset_x": 0.2, "offset_y": -0.1, "size": 0.03 }
  ],
  "glasses": {
    "enabled": true,
    "frameColor": "#1a1a1a",
    "lensColor": "#88ccff",
    "lensOpacity": 20
  },
  "faceMask": {
    "enabled": false,
    "style": "mask2",
    "maskColor": "#7fb5d4",
    "strapColor": "#e6e6e6",
    "opacity": 100
  },
  "earrings": {
    "enabled": false,
    "style": "hoop",
    "sideMode": "both",
    "metalColor": "#d4af37",
    "polish": 82
  },
  "bandana": {
    "enabled": false,
    "style": "paisley",
    "tint": "#ffffff",
    "opacity": 100
  }
}"""

# Variant mode reuses every parameter definition above and replaces only the
# task and the output shape, so the shared prefix stays identical between the
# two prompts and keeps hitting the prompt cache.
AI_VARIANTS_PROMPT = AI_SYSTEM_PROMPT + """

# ══════════════════════════════════════════════════════════════════════
# VARIANT MODE — THIS SECTION OVERRIDES THE OUTPUT FORMAT ABOVE
# ══════════════════════════════════════════════════════════════════════

You are now producing SEVERAL candidate faces in one response, not one face.

A witness will see them side by side and pick whichever is closest to the
person they remember. People are poor at describing individual features but
very good at recognising a face, so the job here is to offer a genuine choice
— not one face plus a handful of near-copies.

## WHAT MAKES A GOOD SET
- Every candidate must be a plausible reading of the SAME description. Never
  contradict something the user stated explicitly.
- Where the description is vague or silent, make a DIFFERENT decision in each
  candidate. That ambiguity is exactly what the witness is there to resolve.
- Vary the big structural things: overall head shape, face length and width,
  jaw, brow, nose bridge and width, eye spacing and set. These drive
  recognition far more than small surface details.
- Two candidates differing by a few points on a few sliders are a wasted slot.
  If you could not tell two of them apart in a lineup, change one of them.
- Give each a short `label` of 2-4 words naming what makes it distinct, for
  example "Narrow jaw, deep-set eyes" or "Broad face, heavy brow".

## OUTPUT FORMAT (strict JSON, nothing else) — REPLACES THE FORMAT ABOVE
{
  "variants": [
    { "label": "Short description", "morphTargets": { "paramName": value, ... } }
  ]
}

Rules for this mode:
1. Output ONLY the "variants" array. No hair, eyebrows, beard, appearance,
   facialMarks, glasses, faceMask, earrings or bandana blocks — those are set
   separately and would be identical across candidates anyway.
2. Produce exactly the number of candidates requested.
3. Each candidate carries its own complete "morphTargets" object. Include every
   parameter you are varying; omit any that should stay at the neutral 50.
4. Integer values 0-100 only.
"""

# Paths
BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR.parent / 'assets'
MODELS_DIR = ASSETS_DIR / 'models'
EXPORTS_DIR = BASE_DIR / 'exports'
BLENDER_SCRIPTS_DIR = BASE_DIR / 'blender_scripts'
CASES_DIR = BASE_DIR / 'cases'

# Ensure directories exist
for d in [EXPORTS_DIR, CASES_DIR, MODELS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Try to find Blender executable
BLENDER_PATH = None
POSSIBLE_BLENDER_PATHS = [
    # Blender 5.x
    r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
    # Blender 4.x
    r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
    # Blender 3.x
    r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
    # macOS / Linux
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "/usr/bin/blender",
    "/snap/bin/blender",
]

# Also search dynamically for any Blender installation
import glob
for pattern in [r"C:\Program Files\Blender Foundation\Blender *\blender.exe"]:
    for path in sorted(glob.glob(pattern), reverse=True):  # newest first
        POSSIBLE_BLENDER_PATHS.insert(0, path)

# An explicit path in .env wins over auto-detection
if os.getenv('BLENDER_PATH'):
    POSSIBLE_BLENDER_PATHS.insert(0, os.getenv('BLENDER_PATH'))

for p in POSSIBLE_BLENDER_PATHS:
    if os.path.exists(p):
        BLENDER_PATH = p
        break


def run_blender_script(script_name, args_dict=None):
    """Execute a Blender Python script in background mode."""
    if not BLENDER_PATH:
        return {"error": "Blender not found. Please install Blender and update the path."}

    script_path = BLENDER_SCRIPTS_DIR / script_name
    if not script_path.exists():
        return {"error": f"Script {script_name} not found"}

    print(f"[Blender] Running {script_name} with Blender at {BLENDER_PATH}")

    # Pass arguments via temp JSON file
    args_file = None
    if args_dict:
        # Normalize all paths to use forward slashes to avoid JSON escape issues
        for key, value in args_dict.items():
            if isinstance(value, str) and '\\' in value:
                args_dict[key] = value.replace('\\', '/')

        args_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(args_dict, args_file, indent=2)
        args_file.close()
        print(f"[Blender] Args file: {args_file.name}")
    
    cmd = [
        BLENDER_PATH,
        '--background',
        '--python', str(script_path)
    ]
    
    if args_file:
        cmd.extend(['--', args_file.name])
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        # Clean up args file
        if args_file:
            os.unlink(args_file.name)
        
        # Parse output for JSON result
        output = result.stdout
        
        # Log Blender output for debugging
        if output.strip():
            print(f"[Blender stdout] {script_name}:")
            for line in output.strip().split('\n'):
                print(f"  {line}")
        if result.stderr and result.stderr.strip():
            print(f"[Blender stderr] {script_name}:")
            for line in result.stderr.strip().split('\n')[-20:]:
                print(f"  {line}")
        
        for line in output.split('\n'):
            if line.startswith('RESULT:'):
                return json.loads(line[7:])
        
        if result.returncode != 0:
            return {"error": result.stderr}
        
        return {"success": True, "output": output}
        
    except subprocess.TimeoutExpired:
        return {"error": "Blender operation timed out"}
    except Exception as e:
        return {"error": str(e)}


# ─── Health Check ──────────────────────────────────────────────────────────────

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "status": "running",
        "blender_available": BLENDER_PATH is not None,
        "blender_path": BLENDER_PATH
    })


# ─── Face Morphing ─────────────────────────────────────────────────────────────

@app.route('/api/morph', methods=['POST'])
def apply_morph():
    """Apply morph targets to the base face mesh using Blender."""
    data = request.json
    morph_params = data.get('morphTargets', {})
    
    result = run_blender_script('apply_morphs.py', {
        'base_model': str(MODELS_DIR / 'base' / 'base_face.obj'),
        'morph_targets': morph_params,
        'output_path': str(EXPORTS_DIR / 'morphed_face.obj')
    })
    
    return jsonify(result)


# ─── Hair System ───────────────────────────────────────────────────────────────

@app.route('/api/hair/generate', methods=['POST'])
def generate_hair():
    """Generate hair particle system using Blender and return downloadable OBJ."""
    data = request.json
    hair_params = data.get('hairParams', {})
    
    output_file = f"hair_mesh_{uuid.uuid4().hex[:8]}.obj"
    output_path = str(EXPORTS_DIR / output_file)
    
    result = run_blender_script('generate_hair.py', {
        'base_model': str(MODELS_DIR / 'base' / 'base_face.obj'),
        'hair_params': hair_params,
        'output_path': output_path
    })
    
    if result.get('success') and os.path.exists(output_path):
        result['hair_obj_url'] = f'/api/hair/download/{output_file}'
        result['filename'] = output_file
    
    return jsonify(result)


@app.route('/api/hair/download/<filename>', methods=['GET'])
def download_hair(filename):
    """Serve a generated hair mesh OBJ file."""
    file_path = EXPORTS_DIR / filename
    if file_path.exists():
        return send_file(str(file_path), mimetype='text/plain')
    return jsonify({"error": "Hair mesh not found"}), 404


# ─── Export ────────────────────────────────────────────────────────────────────

@app.route('/api/export', methods=['POST'])
def export_model():
    """Export the reconstructed face as OBJ/FBX/GLB with all edited features."""
    data = request.json
    format_type = data.get('format', 'obj')
    case_data = data.get('caseData', {})

    print(f"[Export] Starting export as {format_type}")

    export_filename = f"nishaan_export_{uuid.uuid4().hex[:8]}.{format_type}"
    export_path = str(EXPORTS_DIR / export_filename)

    base_model_path = str(MODELS_DIR / 'base' / 'base_face.obj')
    if not os.path.exists(base_model_path):
        error_msg = f"Base model not found at {base_model_path}"
        print(f"[Export] Error: {error_msg}")
        return jsonify({"error": error_msg})

    # Check if a morphed mesh exists (uploaded before this export call)
    morphed_mesh_path = str(EXPORTS_DIR / 'morphed_head_for_render.obj')
    use_morphed = os.path.exists(morphed_mesh_path)

    print(f"[Export] Using morphed mesh: {use_morphed}")
    print(f"[Export] Output path: {export_path}")
    print(f"[Export] MODELS_DIR: {MODELS_DIR}")
    print(f"[Export] MODELS_DIR exists: {MODELS_DIR.exists()}")
    print(f"[Export] Hair style: {case_data.get('hairStyle', 'bald')}")
    print(f"[Export] Beard style: {case_data.get('beardStyle', 'none')}")

    # Prepare the export arguments for Blender
    export_args = {
        'morph_targets': case_data.get('morphTargets', {}),
        'hair_params': case_data.get('hairParams', {}),
        'appearance': case_data.get('appearance', {}),
        'format': format_type,
        'output_path': export_path,
        'base_model': base_model_path,
        'morphed_mesh_path': morphed_mesh_path if use_morphed else '',
        'models_dir': str(MODELS_DIR),
        # Hair data
        'hairStyle': case_data.get('hairStyle', 'bald'),
        'hairColor': case_data.get('hairColor', '#2c1b0e'),
        'hairTransform': case_data.get('hairTransform', None),
        # Beard data
        'beardStyle': case_data.get('beardStyle', 'none'),
        'beardColor': case_data.get('beardColor', '#2c1b0e'),
        'beardParams': case_data.get('beardParams', {}),
        'beardTransform': case_data.get('beardTransform', None),
        # Eyebrow data
        'eyebrowColor': case_data.get('eyebrowColor', '#2c1b0e'),
        'eyebrowParams': case_data.get('eyebrowParams', {}),
        'eyebrowTransform': case_data.get('eyebrowTransform', None),
        # Eye data
        'eyeState': case_data.get('eyeState', {}),
        'eyeTransforms': case_data.get('eyeTransforms', None),
        'eyelashTransforms': case_data.get('eyelashTransforms', None),
        # Skin color
        'skinColor': case_data.get('skinColor', '#d4a574'),
    }

    result = run_blender_script('export_model.py', export_args)

    print(f"[Export] Blender result: {result}")

    # Verify file was actually created
    if result.get('success'):
        if os.path.exists(export_path):
            file_size = os.path.getsize(export_path)
            print(f"[Export] File verified: {export_filename} ({file_size} bytes)")
            result['download_path'] = export_path
            result['filename'] = export_filename
        else:
            print(f"[Export] ERROR: Blender reported success but file not found at {export_path}")
            result['error'] = f"Export failed: file not created"
            result['success'] = False
    elif 'error' not in result:
        result['error'] = 'Export operation failed'
    else:
        print(f"[Export] Error: {result.get('error')}")

    return jsonify(result)


@app.route('/api/decal/bake', methods=['POST'])
def bake_decals():
    """Bake decal textures onto the face mesh skin diffuse map.
    Accepts base OBJ + array of decal texture/projection params.
    Returns baked texture PNG + updated OBJ/MTL."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    decals = data.get('decals', [])
    if not decals:
        return jsonify({"error": "No decals to bake"}), 400

    obj_data = data.get('objData', '')
    skin_color = data.get('skinColor', '#d4a574')
    texture_size = data.get('textureSize', 2048)

    # Save OBJ data to temp file if provided
    obj_path = str(EXPORTS_DIR / 'decal_bake_input.obj')
    if obj_data:
        with open(obj_path, 'w') as f:
            f.write(obj_data)
    elif (EXPORTS_DIR / 'morphed_face.obj').exists():
        obj_path = str(EXPORTS_DIR / 'morphed_face.obj')
    else:
        obj_path = str(MODELS_DIR / 'base' / 'base_face.obj')

    output_dir = str(EXPORTS_DIR / 'decal_bake')

    result = run_blender_script('bake_decals.py', {
        'obj_path': obj_path,
        'output_dir': output_dir,
        'texture_size': texture_size,
        'skin_color': skin_color,
        'decals': decals,
    })

    if result.get('success'):
        result_json_path = Path(output_dir) / 'bake_result.json'
        if result_json_path.exists():
            with open(result_json_path, 'r') as f:
                bake_result = json.load(f)

            # Read the baked texture as base64 for the frontend
            baked_tex_path = bake_result.get('baked_texture', '')
            if baked_tex_path and os.path.exists(baked_tex_path):
                with open(baked_tex_path, 'rb') as f:
                    tex_data = base64.b64encode(f.read()).decode('utf-8')
                bake_result['baked_texture_data'] = f'data:image/png;base64,{tex_data}'

            bake_result['success'] = True
            return jsonify(bake_result)

        return jsonify({"success": True, "message": "Bake completed but no result metadata found"})

    return jsonify(result)


@app.route('/api/export/download/<filename>', methods=['GET'])
def download_export(filename):
    """Download an exported file."""
    file_path = EXPORTS_DIR / filename
    if file_path.exists():
        file_size = file_path.stat().st_size
        print(f"[Download] Serving {filename} ({file_size} bytes)")

        # Determine MIME type based on extension
        if filename.endswith('.obj'):
            mimetype = 'application/octet-stream'
        elif filename.endswith('.fbx'):
            mimetype = 'application/octet-stream'
        elif filename.endswith('.glb'):
            mimetype = 'model/gltf-binary'
        else:
            mimetype = 'application/octet-stream'

        return send_file(str(file_path), as_attachment=True, mimetype=mimetype, download_name=filename)

    print(f"[Download] File not found: {filename} at {file_path}")
    return jsonify({"error": "File not found"}), 404


# ─── Case Management ──────────────────────────────────────────────────────────

@app.route('/api/case/save', methods=['POST'])
def save_case():
    """Save current reconstruction state as a case file."""
    data = request.json
    case_id = data.get('caseId', str(uuid.uuid4()))
    
    case_file = CASES_DIR / f"{case_id}.rfc"
    case_data = {
        'caseId': case_id,
        'caseName': data.get('caseName', 'Untitled Case'),
        'caseNumber': data.get('caseNumber', ''),
        'investigator': data.get('investigator', ''),
        'description': data.get('description', ''),
        'morphTargets': data.get('morphTargets', {}),
        'hairParams': data.get('hairParams', {}),
        'appearance': data.get('appearance', {}),
        'cameraState': data.get('cameraState', {}),
        'notes': data.get('notes', ''),
    }
    
    with open(case_file, 'w') as f:
        json.dump(case_data, f, indent=2)
    
    return jsonify({"success": True, "caseId": case_id, "path": str(case_file)})


@app.route('/api/case/load', methods=['POST'])
def load_case():
    """Load a case file."""
    data = request.json
    case_path = data.get('path', '')
    
    if not os.path.exists(case_path):
        return jsonify({"error": "Case file not found"}), 404
    
    with open(case_path, 'r') as f:
        case_data = json.load(f)
    
    return jsonify(case_data)


# ─── Blender Render ────────────────────────────────────────────────────────────

RENDERS_DIR = BASE_DIR / 'renders'
RENDERS_DIR.mkdir(parents=True, exist_ok=True)


@app.route('/api/render/upload-mesh', methods=['POST'])
def upload_morphed_mesh():
    """Receive the morphed head mesh OBJ from the frontend and save it
    so the Blender render script can import it instead of the base model."""
    data = request.json
    obj_data = data.get('objData', '')
    if not obj_data:
        return jsonify({"error": "No OBJ data provided"}), 400

    mesh_file = EXPORTS_DIR / 'morphed_head_for_render.obj'
    with open(mesh_file, 'w') as f:
        f.write(obj_data)

    return jsonify({"success": True, "path": str(mesh_file).replace('\\', '/')})


@app.route('/api/render', methods=['POST'])
def render_scene():
    """Render the current scene with Blender for a realistic output image.
    If a morphed mesh was uploaded via /api/render/upload-mesh, it will be
    used in place of the base head.glb."""
    data = request.json
    hair_style = data.get('hairStyle', 'hair1')
    hair_color = data.get('hairColor', '#2c1b0e')
    skin_color = data.get('skinColor', '#d4a574')
    engine = data.get('engine', 'EEVEE')
    quality = data.get('quality', 'medium')

    render_filename = f"render_{uuid.uuid4().hex[:8]}"
    render_path = str(RENDERS_DIR / render_filename)

    # Check if a morphed mesh exists (uploaded before this render call)
    morphed_mesh_path = str(EXPORTS_DIR / 'morphed_head_for_render.obj')
    use_morphed = os.path.exists(morphed_mesh_path)

    hair_transform = data.get('hairTransform', None)

    result = run_blender_script('render_scene.py', {
        'hairStyle': hair_style,
        'hairColor': hair_color,
        'skinColor': skin_color,
        'engine': engine,
        'quality': quality,
        'output_path': render_path,
        'models_dir': str(MODELS_DIR),
        'morphed_mesh_path': morphed_mesh_path if use_morphed else '',
        'hairTransform': hair_transform,
    })

    if result.get('error'):
        return jsonify(result), 500

    # Find the output file (Blender may append .png)
    actual_path = result.get('output_path', render_path)
    for candidate in [actual_path, render_path + '.png', render_path + '0001.png']:
        if os.path.exists(candidate):
            actual_path = candidate
            break

    actual_filename = os.path.basename(actual_path)
    result['render_url'] = f'/api/render/download/{actual_filename}'
    result['filename'] = actual_filename
    return jsonify(result)


@app.route('/api/render/download/<filename>', methods=['GET'])
def download_render(filename):
    """Serve a rendered image."""
    file_path = RENDERS_DIR / filename
    if file_path.exists():
        return send_file(str(file_path), mimetype='image/png')
    return jsonify({"error": "Render file not found"}), 404


# ─── AI Face Generation ───────────────────────────────────────────────────────

@app.route('/api/ai/providers', methods=['GET'])
def ai_providers():
    """Return which AI providers are available (have API keys configured)."""
    return jsonify({
        "providers": {
            "groq": {"available": groq_client is not None, "label": "Groq"},
            "gemini": {"available": gemini_client is not None, "label": "Gemini"},
        },
        "default": DEFAULT_AI_PROVIDER,
    })


@app.route('/api/ai/generate', methods=['POST'])
def ai_generate_face():
    """Use AI (Groq or Gemini) to interpret a face description and return parameter values."""
    data = request.json
    prompt = data.get('prompt', '')
    current_state = data.get('currentState', None)
    conversation_history = data.get('history', [])
    reference_images = data.get('referenceImages', None)
    generate_facial_marks = data.get('generateFacialMarks', False)  # New flag for mark generation
    # Backward compatibility with previous single-image payload
    if reference_images is None:
        single_ref = data.get('referenceImage', None)
        reference_images = [single_ref] if single_ref else []
    provider = data.get('provider', DEFAULT_AI_PROVIDER).lower()  # Allow override via request
    model = data.get('model', None)  # Optional specific model override

    if not prompt:
        if not reference_images:
            return jsonify({"error": "No prompt provided"}), 400

    image_payloads = []
    if reference_images:
        try:
            image_payloads = _parse_reference_images(reference_images)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    # Validate provider and check if API key is available
    error = _provider_error(provider)
    if error:
        return error

    # Build user content with current state if available
    user_content = prompt
    if image_payloads:
        img_count = len(image_payloads)
        suffix = 'images are' if img_count > 1 else 'image is'
        if user_content:
            user_content = f"{user_content}\n\n{img_count} reference {suffix} attached."
        else:
            user_content = f"Use the {img_count} attached reference image{'s' if img_count > 1 else ''} to generate the face parameters."

    if generate_facial_marks:
        marks_instruction = "\n\nIMPORTANT: The user wants you to also generate facial marks (scars, birthmarks, moles, etc.). Analyze the reference images for visible marks and include them in your facialMarks output."
        user_content += marks_instruction

    if current_state:
        user_content = (f"Current face state (morphTargets not listed are at their neutral 50):\n"
                        f"{_compact_state(current_state)}\n\nUser request: {prompt}")
        if image_payloads:
            user_content += f"\n\n{len(image_payloads)} reference image{'s are' if len(image_payloads) > 1 else ' is'} attached."
        if generate_facial_marks:
            marks_instruction = "\n\nIMPORTANT: The user wants you to also generate facial marks (scars, birthmarks, moles, etc.). Analyze the reference images for visible marks and include them in your facialMarks output."
            user_content += marks_instruction

    try:
        if provider == 'groq':
            ai_text = _groq_complete(AI_SYSTEM_PROMPT, conversation_history, user_content,
                                     image_payloads, model, 4096)
        else:
            ai_text = _gemini_complete(AI_SYSTEM_PROMPT, conversation_history, user_content,
                                       image_payloads, model)

        if not ai_text:
            return jsonify({
                "error": "The model returned no text output. Try again.",
                "provider": provider,
            }), 500

        # Extract JSON from response (handle potential markdown wrapping)
        if ai_text.startswith('```'):
            lines = ai_text.split('\n')
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith('```') and not in_block:
                    in_block = True
                    continue
                elif line.startswith('```') and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            ai_text = '\n'.join(json_lines)

        face_params = json.loads(ai_text)
        # images (or the "marks from image" option) can justify any change: keep the full answer
        if not image_payloads and not generate_facial_marks:
            _drop_unrequested(face_params, prompt, refining=bool(conversation_history))
        _fill_person_params(face_params)

        return jsonify({
            "success": True,
            "params": face_params,
            "aiResponse": ai_text,
            "provider": provider,
            # the request asked for marks: add them even when the face already has some
            "marksRequested": bool(generate_facial_marks or 'marks' in _mentioned(prompt)),
        })

    except json.JSONDecodeError as e:
        error_msg = f"AI returned invalid JSON: {str(e)}"
        print(f"[AI Error - JSON] {error_msg}")
        print(f"[AI Raw Response] {ai_text if 'ai_text' in locals() else 'No response'}")
        return jsonify({
            "error": error_msg,
            "rawResponse": ai_text if 'ai_text' in locals() else '',
            "provider": provider,
        }), 500
    except Exception as e:
        error_msg = f"{provider.capitalize()} API error: {str(e)}"
        print(f"[AI Error - {provider}] {error_msg}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": error_msg, "provider": provider}), 500


@app.route('/api/ai/variants', methods=['POST'])
def ai_variants():
    """
    Generate several distinct candidate faces in a single call.

    Backs the witness variant picker. The picker only calls this twice at most
    in a normal session — once to open, and again if the witness rejects the
    whole set — because every round after a pick is generated locally by
    jittering the chosen face. Producing the candidates in one response rather
    than one call each is deliberate: asked separately the model tends to
    converge on the same reading of the description, and seeing all of them
    together is what lets it deliberately differentiate.
    """
    data = request.json or {}
    prompt = (data.get('prompt') or '').strip()
    count = max(2, min(8, int(data.get('count', 6))))
    avoid = data.get('avoid') or []
    reference_images = data.get('referenceImages') or []
    provider = data.get('provider', DEFAULT_AI_PROVIDER).lower()
    model = data.get('model', None)

    if not prompt and not reference_images:
        return jsonify({"error": "No description provided"}), 400

    try:
        image_payloads = _parse_reference_images(reference_images)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    error = _provider_error(provider)
    if error:
        return error

    user_content = (
        f"Description of the person:\n{prompt or 'See the attached reference images.'}\n\n"
        f"Produce exactly {count} candidate faces."
    )
    if image_payloads:
        n = len(image_payloads)
        user_content += f"\n\n{n} reference image{'s are' if n > 1 else ' is'} attached."
    if avoid:
        # Without this the model re-derives the same reading of an unchanged
        # description and the second set looks like the first.
        user_content += (
            "\n\nThe witness has already looked at these candidates and said none "
            "of them resemble the person. Produce a set that is clearly different "
            "from all of them — change the structural choices, do not just nudge "
            "the numbers:\n```json\n"
            + json.dumps(avoid, indent=2)
            + "\n```"
        )

    ai_text = ''
    try:
        if provider == 'groq':
            # Several full morph sets in one response needs far more room
            # than the single-face path.
            ai_text = _groq_complete(AI_VARIANTS_PROMPT, [], user_content, image_payloads, model, 16384)
        else:
            ai_text = _gemini_complete(AI_VARIANTS_PROMPT, [], user_content, image_payloads, model)
        if not ai_text:
            return jsonify({"error": "The model returned no text output. Try again.", "provider": provider}), 500

        if ai_text.startswith('```'):
            lines = ai_text.split('\n')
            json_lines, in_block = [], False
            for line in lines:
                if line.startswith('```') and not in_block:
                    in_block = True
                    continue
                if line.startswith('```') and in_block:
                    break
                if in_block:
                    json_lines.append(line)
            ai_text = '\n'.join(json_lines)

        parsed = json.loads(ai_text)
        variants = parsed.get('variants') if isinstance(parsed, dict) else parsed
        if not isinstance(variants, list) or not variants:
            return jsonify({
                "error": "The model did not return a variants array.",
                "rawResponse": ai_text,
                "provider": provider,
            }), 500

        # Keep only well-formed entries so one malformed candidate cannot break
        # the whole set.
        clean = []
        for v in variants:
            if not isinstance(v, dict):
                continue
            morphs = v.get('morphTargets')
            if not isinstance(morphs, dict) or not morphs:
                continue
            clean.append({
                "label": str(v.get('label') or f"Variant {len(clean) + 1}")[:60],
                "morphTargets": {
                    k: max(0, min(100, int(round(float(val)))))
                    for k, val in morphs.items()
                    if isinstance(val, (int, float))
                },
            })

        if not clean:
            return jsonify({
                "error": "The model returned no usable candidates.",
                "rawResponse": ai_text,
                "provider": provider,
            }), 500

        return jsonify({"success": True, "variants": clean, "provider": provider})

    except json.JSONDecodeError as e:
        print(f"[AI Variants - JSON] {e}")
        return jsonify({"error": f"AI returned invalid JSON: {e}", "rawResponse": ai_text, "provider": provider}), 500
    except Exception as e:
        print(f"[AI Variants - {provider}] {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"{provider.capitalize()} API error: {e}", "provider": provider}), 500


_PERSON_DEFAULTS = {"age": 25, "sex": 100, "ancestryAfrican": 33, "ancestryAsian": 33,
                    "ancestryCaucasian": 33, "chinCleft": 0}


def _compact_state(state):
    """Current face state as compact JSON, leaving out sliders still at their default."""
    if not isinstance(state, dict):
        return json.dumps(state, separators=(',', ':'))
    state = dict(state)
    morphs = state.get('morphTargets')
    if isinstance(morphs, dict):
        state['morphTargets'] = {k: v for k, v in morphs.items() if v != _PERSON_DEFAULTS.get(k, 50)}
    return json.dumps(state, separators=(',', ':'))


# Words that show the request is about a feature. On a refinement, parts of the AI answer the
# request does not mention are dropped, so a request like "add a mole" cannot also change the
# age, hair or eye colour. A vague request that names no feature at all is applied as is.
_W = r'(?<![a-z])(?:{})(?![a-z])'.format
_FEATURE_WORDS = {
    'age': _W(r'age[ds]?|old(?:er)?|young(?:er)?|teen(?:age|ager)?s?|elderly|senior|years?|yrs?|'
              r'\d{1,2}s?|twenties|thirties|forties|fifties|sixties|seventies|eighties|middle[- ]aged|kid'),
    'sex': _W(r'man|men|woman|women|male|female|boy|girl|guy|lady|gentleman|masculine|feminine|sex|gender'),
    'ancestry': _W(r'indian|south asian|asian|african|black|white|european|caucasian|chinese|japanese|korean|'
                   r'arab|middle eastern|hispanic|latino|latina|filipino|thai|vietnamese|pakistani|'
                   r'bangladeshi|mixed|ethnic\w*|race|ancestry|origin|descent'),
    'bodyWeight': _W(r'fat|fatter|thin|thinner|slim|slimmer|heavy|heavier|weight|chubby|obese|skinny|plump|'
                     r'overweight|underweight|gaunt|lean|stout|bulky|fleshy|full[- ]faced'),
    'muscle': _W(r'muscle|muscular|athletic|built|strong|frail|bodybuilder|fit|brawny|weak'),
    'face': _W(r'face|faced|head|skull|round|oval|square|heart|v-shaped?|wide|narrow|broad|long|short|'
               r'jowls?|proportions?'),
    'forehead': _W(r'forehead|temples?|brow ridge|hairline'),
    'brow': _W(r'brows?|eyebrows?|unibrow'),
    'eye': _W(r'eyes?|eyelids?|monolid|lids|eye bags|bags|hooded|squint\w*|almond'),
    'nose': _W(r'nose|nostrils?|bridge|hooked|aquiline|snub|button nose|roman'),
    'cheek': _W(r'cheeks?|cheekbones?|nasolabial|smile lines?|dimples?|hollow'),
    'mouth': _W(r'mouth|lips?|smile|philtrum|cupid'),
    'jaw': _W(r'jaw|jawline|chin|chins|jowls?'),
    'ear': _W(r'ears?|earlobes?'),
    'hair': _W(r'hair|haired|hairstyle|haircut|bald|balding|shaved head|curl\w*|wavy|frizzy|straight|'
               r'fringe|bangs|ponytail|braids?|braided|cornrows?|afro|buzz|crew cut|crop|bun|'
               r'receding|blonde?|brunette|ginger|redhead|grey|gray|silver|dreadlocks?'),
    'beard': _W(r'beard|bearded|moustache|mustache|stubble|goatee|shaved|shaven|clean[- ]shaven|'
                r'facial hair|whiskers?|sideburns?'),
    'eyeColor': _W(r'eye colou?r|(?:blue|green|brown|hazel|grey|gray|black|amber)[- ]eyed|'
                   r'(?:blue|green|brown|hazel|grey|gray|black|amber|dark|light) eyes'),
    'lipColor': _W(r'lipstick|lip colou?r|(?:red|pink|dark|pale|nude|purple) lips'),
    'skinColor': _W(r'skin|complexion|tan|tanned|pale|fair|dark[- ]skinned|dusky|wheatish|sunburnt'),
    'marks': _W(r'moles?|birth ?marks?|beauty spots?|port[- ]wine|scars?|scarred|cuts?|stitch\w*|wounds?|'
                r'bruis\w*|burns?|pimples?|acne|spots?|warts?|marks?|blemish\w*|freckles?'),
    'glasses': _W(r'glass(?:es)?|spectacles?|specs|eyewear|sunglass(?:es)?|shades|lenses|frames?'),
    'faceMask': _W(r'mask|masked|covering|covered'),
    'earrings': _W(r'earrings?|ear ?rings?|studs?|hoops?|piercings?|pierced'),
    'bandana': _W(r'bandanas?|kerchief|handkerchief|scarf|cloth'),
}
_MORPH_GROUPS = (
    (('faceWidth', 'faceLength', 'headWidth', 'headLength', 'faceTaper'), 'face'),
    (('forehead', 'temple'), 'forehead'),
    (('brow',), 'brow'),
    (('eye', 'epicanthic'), 'eye'),
    (('nose', 'nostril'), 'nose'),
    (('cheek', 'nasolabial'), 'cheek'),
    (('mouth', 'lip', 'upperLip', 'lowerLip', 'cupid', 'philtrum'), 'mouth'),
    (('jaw', 'chin', 'doubleChin'), 'jaw'),
    (('ear',), 'ear'),
)
_PERSON_KEYS = {'age': 'age', 'sex': 'sex', 'ancestryAfrican': 'ancestry', 'ancestryAsian': 'ancestry',
                'ancestryCaucasian': 'ancestry', 'bodyWeight': 'bodyWeight', 'muscle': 'muscle'}


def _mentioned(prompt):
    text = (prompt or '').lower()
    return {name for name, pattern in _FEATURE_WORDS.items() if re.search(pattern, text)}


def _morph_group(key):
    for prefixes, group in _MORPH_GROUPS:
        if key.startswith(prefixes):
            return group
    return None


def _drop_unrequested(face_params, prompt, refining):
    """Keep only the parts of the AI answer the request is about (see _FEATURE_WORDS).

    New faces keep everything except marks nobody described. Refinements also drop person
    keys, sliders and blocks for features the request does not mention. A request that names
    no feature at all ("try again", "more realistic") is applied unchanged."""
    if not isinstance(face_params, dict):
        return face_params
    said = _mentioned(prompt)
    if 'marks' not in said:
        face_params.pop('facialMarks', None)
    if not refining or not said:
        return face_params
    morphs = face_params.get('morphTargets')
    if isinstance(morphs, dict):
        for key in list(morphs):
            group = _PERSON_KEYS.get(key) or _morph_group(key)
            if group == 'face' and said & {'bodyWeight', 'muscle'}:
                continue  # "fatter" also widens the face
            if group is not None and group not in said:
                morphs.pop(key)
    blocks = {'hair': 'hair', 'eyebrows': 'brow', 'beard': 'beard', 'glasses': 'glasses',
              'faceMask': 'faceMask', 'earrings': 'earrings', 'bandana': 'bandana'}
    for block, group in blocks.items():
        if block in face_params and group not in said:
            face_params.pop(block)
    appearance = face_params.get('appearance')
    if isinstance(appearance, dict):
        for key, group in (('eyeColor', 'eyeColor'), ('lipColor', 'lipColor'),
                           ('skinColor', 'skinColor'), ('ageRange', 'age'), ('sex', 'sex')):
            if key in appearance and group not in said:
                appearance.pop(key)
    return face_params


def _fill_person_params(face_params):
    """Models sometimes report age/sex only in "appearance"; copy them into morphTargets."""
    if not isinstance(face_params, dict):
        return
    morphs = face_params.setdefault('morphTargets', {})
    if not isinstance(morphs, dict):
        return
    appearance = face_params.get('appearance') or {}
    if 'age' not in morphs:
        nums = [int(n) for n in re.findall(r'\d+', str(appearance.get('ageRange', '')))]
        if nums:
            morphs['age'] = max(18, min(90, round(sum(nums[:2]) / len(nums[:2]))))
    if 'sex' not in morphs:
        sex = str(appearance.get('sex', '')).lower()
        if sex.startswith(('f', 'w')):
            morphs['sex'] = 0
        elif sex.startswith('m'):
            morphs['sex'] = 100


def _parse_reference_images(reference_images):
    """Validate and parse frontend-provided image payloads for multimodal models."""
    if not isinstance(reference_images, list):
        raise ValueError("Invalid reference images payload")
    if len(reference_images) == 0:
        return []

    max_images = 10
    if len(reference_images) > max_images:
        raise ValueError(f"Too many reference images. Max allowed is {max_images}.")

    parsed = []
    for reference_image in reference_images:
        parsed.append(_parse_reference_image(reference_image))
    return parsed


def _parse_reference_image(reference_image):
    """Validate and parse a single frontend-provided image payload."""
    if not isinstance(reference_image, dict):
        raise ValueError("Invalid reference image payload")

    data_url = reference_image.get('dataUrl', '')
    mime_type = reference_image.get('mimeType', '')
    if not data_url:
        raise ValueError("Reference image data is empty")

    if data_url.startswith('data:'):
        if ',' not in data_url:
            raise ValueError("Reference image data URL is malformed")
        header, b64_data = data_url.split(',', 1)
        if ';base64' not in header:
            raise ValueError("Reference image must be base64 encoded")
        detected_mime = header[5:].split(';')[0]
        if not mime_type:
            mime_type = detected_mime
    else:
        b64_data = data_url

    if mime_type == 'image/jpg':
        mime_type = 'image/jpeg'

    allowed = {'image/png', 'image/jpeg', 'image/webp'}
    if mime_type not in allowed:
        raise ValueError("Unsupported reference image format. Use PNG, JPEG, or WEBP.")

    try:
        raw_bytes = base64.b64decode(b64_data, validate=True)
    except Exception:
        raise ValueError("Reference image payload is not valid base64 data")

    if len(raw_bytes) > 5 * 1024 * 1024:
        raise ValueError("Reference image is too large. Please use an image under 5MB.")

    return {
        "mime_type": mime_type,
        "base64_data": b64_data,
        "raw_bytes": raw_bytes,
    }


# ─── Speech-to-Text ──────────────────────────────────────────────────────────

@app.route('/api/speech/transcribe', methods=['POST'])
def transcribe_speech():
    """Transcribe recorded audio to text.

    Uses Groq Whisper when a Groq key is configured (accepts the browser's
    WebM/Opus recording directly); otherwise falls back to the free Google
    Web Speech endpoint via SpeechRecognition (needs ffmpeg for WebM).
    """
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files['audio']
    filename = audio_file.filename or 'audio.webm'
    audio_bytes = audio_file.read()
    if len(audio_bytes) < 1000:
        return jsonify({"error": "Recording was empty. Hold the mic button a little longer."}), 400

    if groq_client:
        try:
            result = groq_client.audio.transcriptions.create(
                file=(filename, audio_bytes),
                model=GROQ_WHISPER_MODEL,
                language='en',
                # Biases recognition toward the vocabulary witnesses use
                prompt="A witness describing a person's face: age, build, skin tone, "
                       "hair, eyes, nose, jaw, chin, lips, beard, scars, glasses.",
                response_format='json',
                temperature=0.0,
            )
            text = (getattr(result, 'text', '') or '').strip()
            if not text:
                return jsonify({"error": "No speech detected. Try speaking closer to the microphone."}), 400
            return jsonify({"success": True, "text": text, "engine": GROQ_WHISPER_MODEL})
        except Exception as e:
            print(f"[Speech] Groq Whisper failed, falling back to Google: {e}")

    recognizer = sr.Recognizer()
    suffix = '.webm' if 'webm' in filename else '.wav'
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    wav_path = tmp_path
    try:
        # Convert webm to wav if needed (using ffmpeg via pydub)
        if suffix == '.webm':
            from pydub import AudioSegment
            wav_path = tmp_path.replace('.webm', '.wav')
            audio_seg = AudioSegment.from_file(tmp_path, format='webm')
            audio_seg.export(wav_path, format='wav')

        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
        text = recognizer.recognize_google(audio_data)
        return jsonify({"success": True, "text": text, "engine": "google"})
    except sr.UnknownValueError:
        return jsonify({"error": "Could not understand audio. Try speaking more clearly."}), 400
    except sr.RequestError as e:
        return jsonify({"error": f"Speech service error: {str(e)}"}), 500
    except Exception as e:
        hint = "" if groq_client else " Add GROQ_API_KEY to .env to use Whisper transcription."
        return jsonify({"error": f"Audio processing error: {str(e)}.{hint}"}), 500
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        if wav_path != tmp_path and os.path.exists(wav_path):
            os.unlink(wav_path)


# ─── Blender Status ───────────────────────────────────────────────────────────

@app.route('/api/blender/config', methods=['POST'])
def set_blender_path():
    """Manually set the Blender executable path."""
    global BLENDER_PATH
    data = request.json
    path = data.get('path', '')
    
    if os.path.exists(path):
        BLENDER_PATH = path
        return jsonify({"success": True, "blender_path": BLENDER_PATH})
    
    return jsonify({"error": "Path does not exist"}), 400


if __name__ == '__main__':
    print("=" * 60)
    print("  Nishaan — Backend Server")
    print(f"  Blender: {'Found at ' + BLENDER_PATH if BLENDER_PATH else 'NOT FOUND'}")
    print(f"  AI Provider: {DEFAULT_AI_PROVIDER.upper()}")
    print(f"  - Groq: {'✓ Ready' if groq_client else '✗ No API key'}")
    print(f"  - Gemini: {'✓ Ready' if gemini_client else '✗ No API key'}")
    print("=" * 60)
    app.run(host='127.0.0.1', port=5001, debug=False)
