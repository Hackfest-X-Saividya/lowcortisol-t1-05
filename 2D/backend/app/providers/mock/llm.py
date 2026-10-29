"""Deterministic mock LLM.

Implements every task in ``services/interview/prompts.py`` with keyword rules so the whole
flow runs offline. The rules are intentionally simple; they only need to be plausible and
repeatable for demos and tests.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from app.providers.base import LLMRequest, LLMResult
from app.providers.mock.asr import load_fixtures
from app.services.interview.fields import FIELDS

AMOUNT_WORDS: list[tuple[tuple[str, ...], float]] = [
    (("bahut", "बहुत", "tumba", "ತುಂಬಾ", "a lot", "lot", "much", "very"), 0.15),
    (("aur", "और", "innu", "ಇನ್ನೂ", "more", "further"), 0.10),
    (
        (
            "thoda",
            "थोड़ा",
            "thodi",
            "थोड़ी",
            "swalpa",
            "ಸ್ವಲ್ಪ",
            "a little",
            "little",
            "a bit",
            "bit",
            "slightly",
        ),
        0.05,
    ),
]

REGION_WORDS: dict[str, tuple[str, ...]] = {
    "jaw": (
        "jaw",
        "jabda",
        "जबड़ा",
        "जबड़े",
        "dawade",
        "ದವಡೆ",
        "chin",
        "thodi",
        "ठोड़ी",
        "gadda",
        "ಗಲ್ಲ",
    ),
    "eyes": ("eye", "aankh", "आंख", "आँख", "kannu", "ಕಣ್ಣು"),
    "nose": ("nose", "naak", "नाक", "moogu", "ಮೂಗು"),
    "mouth": ("mouth", "lip", "hoth", "होंठ", "honth", "muh", "मुंह", "tuti", "ತುಟಿ", "baayi", "ಬಾಯಿ"),
    "brows": ("brow", "bhaun", "भौं", "भौंह", "bhavein", "hubbu", "ಹುಬ್ಬು"),
    "face_shape": ("face", "chehra", "चेहरा", "mukha", "ಮುಖ"),
    "hair": (
        "hair",
        "baal",
        "बाल",
        "koodalu",
        "ಕೂದಲು",
        "beard",
        "dadhi",
        "दाढ़ी",
        "gadda",
        "ಗಡ್ಡ",
        "moustache",
        "mooch",
        "मूंछ",
        "meese",
        "ಮೀಸೆ",
    ),
    "skin": ("skin", "rang", "रंग", "complexion", "banna", "ಬಣ್ಣ", "twacha", "त्वचा"),
    "ears": ("ear", "kaan", "कान", "kivi", "ಕಿವಿ"),
    "marks": (
        "scar",
        "nishan",
        "निशान",
        "kale",
        "ಕಲೆ",
        "mole",
        "til",
        "तिल",
        "machche",
        "ಮಚ್ಚೆ",
        "tilak",
        "तिलक",
    ),
}

OVERLAY_WORDS: list[tuple[tuple[str, ...], str, str]] = [
    (("sunglass", "goggle", "kala chashma", "काला चश्मा"), "spectacles_square", "eyes"),
    (
        ("spectacle", "glasses", "chashma", "चश्मा", "kannadaka", "ಕನ್ನಡಕ", "specs"),
        "spectacles_round",
        "eyes",
    ),
    (("helmet", "हेलमेट", "ಹೆಲ್ಮೆಟ್"), "helmet", "hair"),
    (("turban", "pagdi", "पगड़ी", "ಪೇಟ"), "turban", "hair"),
    (("cap", "topi", "टोपी", "ಟೋಪಿ", "hat"), "cap", "hair"),
    (
        ("mask", "cloth", "rumal", "रुमाल", "kapda", "कपड़ा", "batte", "ಬಟ್ಟೆ", "scarf"),
        "face_cloth",
        "mouth",
    ),
    (
        ("thick moustache", "badi mooch", "बड़ी मूंछ", "dappa meese", "ದಪ್ಪ ಮೀಸೆ"),
        "moustache_thick",
        "hair",
    ),
    (("moustache", "mustache", "mooch", "मूंछ", "meese", "ಮೀಸೆ"), "moustache_thin", "hair"),
    (
        (
            "full beard",
            "lambi dadhi",
            "लंबी दाढ़ी",
            "badi dadhi",
            "बड़ी दाढ़ी",
            "udda gadda",
            "ಉದ್ದ ಗಡ್ಡ",
        ),
        "beard_full",
        "hair",
    ),
    (("beard", "dadhi", "दाढ़ी", "gadda", "ಗಡ್ಡ", "goatee", "stubble"), "beard_short", "hair"),
    (("scar", "nishan", "निशान", "kale", "ಕಲೆ", "cut mark"), "scar", "marks"),
    (("mole", "til", "तिल", "machche", "ಮಚ್ಚೆ"), "mole", "marks"),
    (("tilak", "तिलक", "ತಿಲಕ", "bindi"), "tilak", "marks"),
    (("earring", "bali", "बाली", "jhumka", "ole", "ಓಲೆ"), "earring", "ears"),
]

POSITION_WORDS: dict[str, tuple[str, ...]] = {
    "left_cheek": ("left cheek", "baen gaal", "बाएं गाल", "बायें गाल", "eda kenne", "ಎಡ ಕೆನ್ನೆ"),
    "right_cheek": ("right cheek", "daen gaal", "दाएं गाल", "दायें गाल", "bala kenne", "ಬಲ ಕೆನ್ನೆ"),
    "forehead": ("forehead", "matha", "माथा", "माथे", "hane", "ಹಣೆ"),
    "chin": ("chin", "thodi", "ठोड़ी", "gadda", "ಗಲ್ಲ"),
}

PARAM_RULES: list[tuple[str, tuple[str, ...], str, int]] = [
    # region, trigger words, param, direction
    ("jaw", ("wider", "wide", "broad", "chauda", "चौड़ा", "agala", "ಅಗಲ"), "jaw_width", 1),
    (
        "jaw",
        ("narrow", "thinner", "patla", "पतला", "sanna", "ಸಣ್ಣ", "chhota", "छोटा"),
        "jaw_width",
        -1,
    ),
    ("face_shape", ("longer", "long", "lamba", "लंबा", "udda", "ಉದ್ದ"), "face_length", 1),
    (
        "face_shape",
        ("shorter", "short", "round", "chhota", "छोटा", "gol", "गोल", "chikka", "ಚಿಕ್ಕ"),
        "face_length",
        -1,
    ),
    ("eyes", ("bigger", "big", "large", "badi", "बड़ी", "dodda", "ದೊಡ್ಡ"), "eye_size", 1),
    ("eyes", ("smaller", "small", "chhoti", "छोटी", "chikka", "ಚಿಕ್ಕ", "narrow"), "eye_size", -1),
    ("eyes", ("apart", "farther", "door", "दूर", "wider apart", "doora", "ದೂರ"), "eye_spacing", 1),
    ("eyes", ("closer", "paas", "पास", "hattira", "ಹತ್ತಿರ", "close together"), "eye_spacing", -1),
    ("nose", ("longer", "long", "lambi", "लंबी", "udda", "ಉದ್ದ"), "nose_length", 1),
    ("nose", ("shorter", "short", "chhoti", "छोटी", "chikka", "ಚಿಕ್ಕ"), "nose_length", -1),
    ("nose", ("wider", "wide", "broad", "chaudi", "चौड़ी", "agala", "ಅಗಲ", "flat"), "nose_width", 1),
    ("nose", ("narrow", "thin", "sharp", "patli", "पतली", "sanna", "ಸಣ್ಣ"), "nose_width", -1),
    (
        "mouth",
        ("fuller", "full", "thick", "mote", "मोटे", "dappa", "ದಪ್ಪ", "bigger"),
        "lip_fullness",
        1,
    ),
    (
        "mouth",
        ("thinner", "thin", "patle", "पतले", "tellage", "ತೆಳ್ಳಗೆ", "smaller"),
        "lip_fullness",
        -1,
    ),
    ("brows", ("higher", "up", "upar", "ऊपर", "mele", "ಮೇಲೆ", "raise"), "brow_height", 1),
    ("brows", ("lower", "down", "neeche", "नीचे", "kelage", "ಕೆಳಗೆ"), "brow_height", -1),
]

INPAINT_WORDS = (
    "grey",
    "gray",
    "white hair",
    "safed",
    "सफेद",
    "bili",
    "ಬಿಳಿ",
    "curly",
    "ghunghrale",
    "घुंघराले",
    "bald",
    "ganja",
    "गंजा",
    "darker",
    "lighter",
    "fairer",
    "kala",
    "काला",
    "gora",
    "गोरा",
    "kappu",
    "ಕಪ್ಪು",
    "bili",
    "stubble",
    "longer hair",
    "shorter hair",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?।])\s+")
_NUMBER_WORDS = {"twenty": "20", "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60"}


def _first_sentence_with(text: str, needle: str) -> str:
    for s in _SENTENCE_SPLIT.split(text):
        if needle.lower() in s.lower():
            return s.strip()
    return ""


def _amount(text: str) -> float | None:
    t = f" {text.lower()} "
    for words, amt in AMOUNT_WORDS:
        for w in words:
            if f" {w} " in t or w in t and len(w) > 4:
                return amt
    return None


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    t = text.lower()
    return any(w.lower() in t for w in words)


class MockLLM:
    name = "mock"
    model = "mock-rules"

    async def complete_json(self, req: LLMRequest) -> LLMResult:
        handler = getattr(self, f"_task_{req.task}", None)
        if handler is None:
            raise ValueError(f"mock LLM has no handler for task {req.task}")
        data = handler(req.payload)
        return LLMResult(data=data, provider=self.name, model=self.model)

    # ---- translate ---------------------------------------------------------------------

    def _task_translate(self, p: dict[str, Any]) -> dict[str, Any]:
        text, src, tgt = p["text"], p["source_lang"], p["target_lang"]
        if src == tgt:
            return {"translation": text}
        fixtures = load_fixtures()
        for lang, entries in fixtures.items():
            for entry in entries.values():
                if src != "en" and entry["original"].strip() == text.strip() and lang == src:
                    return {"translation": entry["english"]}
                if src == "en" and tgt == lang and entry["english"].strip() == text.strip():
                    return {"translation": entry["original"]}
        if tgt == "en":
            return {"translation": text}
        return {"translation": f"[{tgt}] {text}"}

    # ---- feature sheet -------------------------------------------------------------------

    def _task_extract_feature_sheet(self, p: dict[str, Any]) -> dict[str, Any]:
        text = p.get("statement_english") or p.get("statement_original") or ""
        low = f" {text.lower()} "
        out: dict[str, Any] = {}
        for f in FIELDS:
            for value, kws in f.value_keywords.items():
                hit = next((kw for kw in kws if kw.lower() in low), None)
                if hit:
                    out[f.key] = {
                        "value": value,
                        "confidence": "medium",
                        "source_text": _first_sentence_with(text, hit),
                    }
                    break
        m = re.search(
            r"\b(\d{2}|twenty|thirty|forty|fifty|sixty)\b[\w\s-]{0,12}?(years|year|yrs|saal|varsha)",
            low,
        )
        if m:
            age = int(_NUMBER_WORDS.get(m.group(1), m.group(1)))
            bucket = (
                "under_20"
                if age < 20
                else "20_30"
                if age < 30
                else "30_40"
                if age < 40
                else "40_50"
                if age < 50
                else "over_50"
            )
            out["age_range"] = {
                "value": bucket,
                "confidence": "medium",
                "source_text": _first_sentence_with(text, m.group(0)),
            }
        m = re.search(r"(\d+(?:\.\d+)?)\s*(m\b|metre|meter|feet|ft)", low)
        if m:
            val = float(m.group(1))
            if m.group(2).startswith("f"):
                val = round(val * 0.3048, 1)
            out["distance_m"] = {
                "value": str(val),
                "confidence": "medium",
                "source_text": _first_sentence_with(text, m.group(0)),
            }
        if "scar" in low:
            pos = next((k for k, ws in POSITION_WORDS.items() if _has_any(low, ws)), "")
            out["scars"] = {
                "value": f"scar {pos.replace('_', ' ')}".strip(),
                "confidence": "medium",
                "source_text": _first_sentence_with(text, "scar"),
            }
        if "mole" in low:
            pos = next((k for k, ws in POSITION_WORDS.items() if _has_any(low, ws)), "")
            out["moles"] = {
                "value": f"mole {pos.replace('_', ' ')}".strip(),
                "confidence": "medium",
                "source_text": _first_sentence_with(text, "mole"),
            }
        for colour in ("blue", "red", "white", "black", "green", "yellow", "grey", "brown"):
            m2 = re.search(rf"{colour}\s+(shirt|t-shirt|kurta|jacket)", low)
            if m2:
                out["clothing"] = {
                    "value": m2.group(0),
                    "confidence": "medium",
                    "source_text": _first_sentence_with(text, m2.group(0)),
                }
                break
        if "standing" in low or "sitting" in low:
            m3 = re.search(
                r"(standing|sitting)\s+(near|behind|at|inside|outside|by)\s+([^,.]+)", low
            )
            if m3:
                out["witness_position"] = {
                    "value": m3.group(0).strip(),
                    "confidence": "medium",
                    "source_text": _first_sentence_with(text, m3.group(1)),
                }
        events = [
            s.strip()
            for s in _SENTENCE_SPLIT.split(text)
            if re.search(r"\b(came|went|stood|took|ran|entered|left|grabbed|walked)\b", s.lower())
        ]
        if events:
            out["events"] = {
                "value": " | ".join(events[:5]),
                "confidence": "medium",
                "source_text": events[0],
            }
        objs = [
            w
            for w in (
                "counter",
                "table",
                "door",
                "window",
                "shelf",
                "chair",
                "bike",
                "car",
                "bed",
                "cupboard",
            )
            if w in low
        ]
        if objs:
            out["objects"] = {
                "value": ", ".join(objs),
                "confidence": "medium",
                "source_text": _first_sentence_with(text, objs[0]),
            }
        return {"fields": out}

    # ---- questions -----------------------------------------------------------------------

    def _task_interview_turn(self, p: dict[str, Any]) -> dict[str, Any]:
        """Offline version of the live interview turn: keyword extraction, keyword edits,
        and the safe template question for the first field still missing."""
        from app.services.interview.local_templates import ACK, UPDATED, line, question_for

        words = str(p.get("witness_words", ""))
        lang = str(p.get("language", "en"))
        english = self._task_translate({"text": words, "source_lang": lang, "target_lang": "en"})[
            "translation"
        ]
        fields = self._task_extract_feature_sheet(
            {"statement_english": english, "statement_original": words}
        )["fields"]
        low = f" {english.lower()} {words.lower()} "
        last = p.get("last_question") or {}
        if last.get("field") and _has_any(
            low, ("don't remember", "do not remember", "not sure", "ನೆನಪಿಲ್ಲ", "याद नहीं")
        ):
            fields[last["field"]] = {
                "value": "not_remembered",
                "confidence": "not_remembered",
                "source_text": words,
            }
        adjustments = []
        if _has_any(
            low,
            (
                "make",
                "more",
                "bit",
                "little",
                "lot",
                "change",
                "karo",
                "ಮಾಡಿ",
                "करो",
                "wider",
                "narrower",
                "longer",
                "shorter",
                "bigger",
                "smaller",
            ),
        ):
            for region, triggers, param, direction in PARAM_RULES:
                region_words = REGION_WORDS.get(region, ())
                if _has_any(low, region_words) and _has_any(low, triggers):
                    amt = _amount(low) or 0.05
                    adjustments.append({"param": param, "amount": amt * direction})
                    break
        pending = [f["key"] for f in p.get("next_fields", []) if f.get("key") not in fields]
        if pending:
            ask = pending[0]
            reply_local = f"{line(UPDATED if adjustments else ACK, lang)} {question_for(ask, lang)}"
            reply_en = f"{line(UPDATED if adjustments else ACK, 'en')} {question_for(ask, 'en')}"
        else:
            from app.services.interview.local_templates import REVIEW

            ask = "review"
            reply_local = line(REVIEW, lang)
            reply_en = line(REVIEW, "en")
        return {
            "english": english,
            "fields": fields,
            "adjustments": adjustments,
            "reply_local": reply_local,
            "reply_en": reply_en,
            "ask_field": ask,
        }

    def _task_quick_fields(self, p: dict[str, Any]) -> dict[str, Any]:
        turn = self._task_interview_turn(
            {"witness_words": p.get("witness_words", ""), "language": "en", "next_fields": []}
        )
        return {"fields": turn["fields"], "adjustments": turn["adjustments"]}

    def _task_phrase_question(self, p: dict[str, Any]) -> dict[str, Any]:
        desc = str(p.get("field_description", "that feature")).lower()
        key = p.get("field_key", "")
        if p.get("reason") == "contradiction":
            return {
                "question_en": f"Earlier answers about the {desc} did not quite match. "
                f"What do you remember about it?"
            }
        if key in ("distance_m",):
            return {"question_en": "About how far away was the person from you?"}
        return {"question_en": f"What do you remember about the person's {desc}?"}

    def _task_leading_check(self, p: dict[str, Any]) -> dict[str, Any]:
        from app.services.interview.leading_check import rule_check

        q = p.get("question_en", "")
        hit = rule_check(q, p.get("field_key", ""))
        return {"leading": hit is not None, "reason": hit or ""}

    # ---- edit routing ----------------------------------------------------------------------

    def _task_route_edit(self, p: dict[str, Any]) -> dict[str, Any]:
        text = f"{p.get('utterance_original', '')} {p.get('utterance_en', '')}"
        low = f" {text.lower()} "
        locks = set(p.get("locked_regions") or [])
        base: dict[str, Any] = {
            "region": "",
            "type": "none",
            "param": "",
            "amount": None,
            "direction": 1,
            "overlay_id": "",
            "overlay_params": {},
            "prompt": "",
            "symmetric": True,
            "needs_choice": False,
            "message": "",
        }
        # 1) accessories / marks -> overlay
        for words, overlay_id, region in OVERLAY_WORDS:
            if _has_any(low, words):
                removing = _has_any(
                    low,
                    (
                        "remove",
                        "hatao",
                        "हटाओ",
                        "tegeyiri",
                        "ತೆಗೆಯಿರಿ",
                        "without",
                        "nahi",
                        "नहीं",
                        "no ",
                    ),
                )
                if region == "marks" and "marks" in locks:
                    return {
                        **base,
                        "region": region,
                        "message": "The marks are locked. Unlock them first.",
                    }
                params: dict[str, Any] = {"size": 1.0}
                pos = next((k for k, ws in POSITION_WORDS.items() if _has_any(low, ws)), None)
                if pos:
                    params["position"] = pos
                if removing:
                    params["remove"] = True
                return {
                    **base,
                    "region": region,
                    "type": "overlay",
                    "overlay_id": overlay_id,
                    "overlay_params": params,
                }
        # 2) geometric
        region = next((r for r, ws in REGION_WORDS.items() if _has_any(low, ws)), "")
        if region in ("hair", "skin") or (not region and _has_any(low, INPAINT_WORDS)):
            region = region or "hair"
            if region in locks:
                return {
                    **base,
                    "region": region,
                    "message": f"The {region} is locked. Unlock it first.",
                }
            return {
                **base,
                "region": region,
                "type": "inpaint",
                "prompt": (p.get("utterance_en") or p.get("utterance_original") or "")[:120],
            }
        for r, words, param, direction in PARAM_RULES:
            if (region == r or not region) and _has_any(low, words):
                if r in locks:
                    return {
                        **base,
                        "region": r,
                        "message": f"The {r.replace('_', ' ')} is locked. Unlock it first.",
                    }
                amt = _amount(low)
                return {
                    **base,
                    "region": r,
                    "type": "geometric",
                    "param": param,
                    "amount": amt,
                    "direction": direction,
                    "needs_choice": amt is None,
                }
        if region:
            if region in locks:
                return {
                    **base,
                    "region": region,
                    "message": f"The {region.replace('_', ' ')} is locked. Unlock it first.",
                }
            return {
                **base,
                "region": region,
                "type": "none",
                "message": "I understood the region but not the change. Try 'wider', "
                "'narrower', 'bigger' or 'smaller'.",
            }
        return {**base, "message": "Sorry, I could not understand that edit."}

    # ---- scene -------------------------------------------------------------------------------

    def _task_build_scene(self, p: dict[str, Any]) -> dict[str, Any]:
        text = f"{p.get('description_en', '')} {p.get('description_original', '')}".lower()
        templates: dict[str, Any] = p.get("templates") or {}
        name = "room"
        for key, words in (
            ("shop", ("shop", "store", "counter", "dukaan", "दुकान", "angadi", "ಅಂಗಡಿ")),
            ("street", ("street", "road", "lane", "sadak", "सड़क", "raste", "ರಸ್ತೆ")),
            ("junction", ("junction", "crossing", "circle", "chauraha", "चौराहा", "signal")),
            ("house", ("house", "home", "flat", "ghar", "घर", "mane", "ಮನೆ")),
            ("room", ("room", "kamra", "कमरा")),
        ):
            if any(w in text for w in words):
                name = key
                break
        scene: dict[str, Any] = copy.deepcopy(
            templates.get(name) or next(iter(templates.values()), {})
        )
        scene["template"] = name
        people = scene.setdefault("people", [])
        if not any(pp.get("role") == "witness" for pp in people):
            people.append(
                {
                    "id": "witness",
                    "role": "witness",
                    "pos": [1.0, 0.0, 1.0],
                    "facing_deg": 0.0,
                    "eye_height_m": 1.5,
                }
            )
        if not any(pp.get("role") == "suspect" for pp in people):
            people.append(
                {
                    "id": "suspect",
                    "role": "suspect",
                    "pos": [1.0, 0.0, 3.5],
                    "facing_deg": 180.0,
                    "eye_height_m": 1.6,
                }
            )
        events = scene.setdefault("events", [])
        if not events:
            sentences = [
                s.strip()
                for s in _SENTENCE_SPLIT.split(p.get("description_en", ""))
                if re.search(r"\b(came|went|stood|took|ran|entered|left|walked)\b", s.lower())
            ]
            for i, s in enumerate(sentences[:5], start=1):
                events.append({"step": i, "text": s, "positions": {}})
        return {"scene": scene}

    def _task_scene_command(self, p: dict[str, Any]) -> dict[str, Any]:
        text = f"{p.get('utterance_original', '')} {p.get('utterance_en', '')}".lower()
        scene = p.get("scene") or {}
        amt = {0.05: 0.5, 0.10: 1.0, 0.15: 2.0}.get(_amount(text) or 0.10, 1.0)
        dirs = {
            "left": (("left", "baen", "बाईं", "बाएं", "edakke", "ಎಡಕ್ಕೆ"), (-amt, 0.0)),
            "right": (("right", "daen", "दाईं", "दाएं", "balakke", "ಬಲಕ್ಕೆ"), (amt, 0.0)),
            "forward": (
                ("forward", "aage", "आगे", "munde", "ಮುಂದೆ", "closer", "towards"),
                (0.0, -amt),
            ),
            "back": (("back", "peeche", "पीछे", "hinde", "ಹಿಂದೆ", "away", "further"), (0.0, amt)),
        }
        delta = next((d for _, (ws, d) in dirs.items() if any(w in text for w in ws)), None)
        targets = [("objects", o) for o in scene.get("objects", [])] + [
            ("people", pp) for pp in scene.get("people", [])
        ]
        target = None
        for coll, item in targets:
            words = {
                str(item.get("id", "")).lower(),
                str(item.get("type", "")).lower(),
                str(item.get("role", "")).lower(),
            }
            words.discard("")
            if any(w and w in text for w in words):
                target = (coll, item)
                break
        if target is None or delta is None:
            return {"patch": [], "explanation": "Could not identify an object and a direction."}
        coll, item = target
        idx = scene[coll].index(item)
        pos = list(item.get("pos", [0, 0, 0]))
        new_pos = [round(pos[0] + delta[0], 2), pos[1], round(pos[2] + delta[1], 2)]
        return {
            "patch": [{"op": "replace", "path": f"/{coll}/{idx}/pos", "value": new_pos}],
            "explanation": f"Moved {item.get('id')} by {delta}.",
        }
