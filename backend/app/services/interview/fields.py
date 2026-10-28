"""Feature sheet fields, interview order and the feature-card catalogue.

Each feature sheet entry holds ``{value, confidence, source_text, updated_at}``. The
interview engine walks ``FIELDS`` in order (situation -> overall -> face -> marks), skipping
filled fields. Face-feature questions carry option cards from ``CARD_CATALOG`` (the
frontend draws the cards; the backend only knows their ids and labels). Every question
also offers ``not_remembered``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

STAGES = ("situation", "overall", "face", "marks", "check")
CONFIDENCES = ("high", "medium", "low", "not_remembered")
NOT_REMEMBERED = "not_remembered"


@dataclass(frozen=True)
class Card:
    id: str
    label: str
    value: str


@dataclass(frozen=True)
class FieldDef:
    key: str
    stage: str
    label: str
    description: str
    safe_question: str  # non-leading fallback template
    cards: tuple[Card, ...] = ()
    sketch_feature: str | None = None  # feature lock name this field maps to
    asked: bool = True  # scene fields are extracted but never asked by the sketch interview
    value_keywords: dict[str, tuple[str, ...]] = field(default_factory=dict)


def _cards(prefix: str, items: list[tuple[str, str]]) -> tuple[Card, ...]:
    return tuple(Card(id=f"{prefix}_{v}", label=label, value=v) for v, label in items)


FIELDS: list[FieldDef] = [
    # ---- situation -------------------------------------------------------------------
    FieldDef(
        "witness_position",
        "situation",
        "Where you were",
        "Where the witness was standing or sitting when they saw the person",
        "Where were you when you saw the person?",
        value_keywords={
            "near": ("near", "next to", "beside"),
            "inside": ("inside",),
            "outside": ("outside",),
        },
    ),
    FieldDef(
        "lighting",
        "situation",
        "Lighting",
        "Lighting conditions at the time (daylight, dim, street light, dark)",
        "What was the lighting like at that time?",
        cards=_cards(
            "lighting",
            [
                ("daylight", "Daylight"),
                ("bright_indoor", "Bright indoor"),
                ("dim", "Dim"),
                ("street_light", "Street light"),
                ("dark", "Dark"),
            ],
        ),
        value_keywords={
            "daylight": ("daylight", "sunny", "daytime"),
            "dim": ("dim", "low"),
            "dark": ("dark", "night"),
            "bright_indoor": ("bright", "okay", "fine", "good light"),
        },
    ),
    FieldDef(
        "distance_m",
        "situation",
        "Distance",
        "Approximate distance between the witness and the person, in metres",
        "About how far away was the person from you?",
        cards=_cards(
            "distance",
            [
                ("1", "Within arm's reach"),
                ("3", "About 3 metres"),
                ("5", "About 5 metres"),
                ("10", "About 10 metres"),
                ("20", "20 metres or more"),
            ],
        ),
    ),
    FieldDef(
        "view_duration",
        "situation",
        "How long you saw them",
        "How long the witness could see the person",
        "For about how long could you see the person?",
        cards=_cards(
            "duration",
            [
                ("seconds", "A few seconds"),
                ("under_minute", "Under a minute"),
                ("minutes", "A few minutes"),
                ("long", "Longer"),
            ],
        ),
    ),
    FieldDef(
        "view_angle",
        "situation",
        "Angle",
        "From which direction the witness saw the person's face (front, side, behind)",
        "From which side did you see the person's face?",
        cards=_cards(
            "angle",
            [
                ("front", "From the front"),
                ("side", "From the side"),
                ("behind", "Mostly from behind"),
                ("mixed", "Different angles"),
            ],
        ),
        value_keywords={
            "front": ("front", "facing"),
            "side": ("side", "profile"),
            "behind": ("behind", "back"),
        },
    ),
    # ---- overall ----------------------------------------------------------------------
    FieldDef(
        "gender",
        "overall",
        "Gender",
        "Apparent gender of the person",
        "How would you describe the person overall?",
        cards=_cards("gender", [("male", "Man"), ("female", "Woman"), ("unsure", "Not sure")]),
        value_keywords={
            "male": ("man", "male", "boy", " he ", "his"),
            "female": ("woman", "female", "girl", " she ", "her"),
        },
    ),
    FieldDef(
        "age_range",
        "overall",
        "Age",
        "Approximate age range",
        "About how old did the person seem?",
        cards=_cards(
            "age",
            [
                ("under_20", "Under 20"),
                ("20_30", "20 to 30"),
                ("30_40", "30 to 40"),
                ("40_50", "40 to 50"),
                ("over_50", "Over 50"),
            ],
        ),
        value_keywords={
            "20_30": ("young", "in his twenties", "in her twenties"),
            "over_50": ("old man", "old woman", "elderly"),
            "40_50": ("middle aged", "middle-aged", "in his forties"),
        },
    ),
    FieldDef(
        "height_relative",
        "overall",
        "Height",
        "Height compared with the witness or others",
        "How tall was the person compared with you?",
        cards=_cards(
            "height",
            [
                ("shorter", "Shorter than me"),
                ("same", "About my height"),
                ("taller", "Taller than me"),
                ("much_taller", "Much taller"),
            ],
        ),
        value_keywords={
            "taller": ("tall",),
            "shorter": ("short",),
            "same": ("average height", "medium height"),
        },
    ),
    FieldDef(
        "build",
        "overall",
        "Build",
        "Body build",
        "What was the person's build like?",
        cards=_cards(
            "build",
            [
                ("slim", "Slim"),
                ("average", "Average"),
                ("heavy", "Heavy"),
                ("muscular", "Muscular"),
            ],
        ),
        value_keywords={
            "slim": ("thin", "slim", "lean", "skinny"),
            "heavy": ("heavy", "fat", "stout", "plump"),
            "muscular": ("muscular", "strong", "well built"),
            "average": ("average build", "medium build"),
        },
    ),
    FieldDef(
        "skin_tone",
        "overall",
        "Skin tone",
        "Skin tone",
        "What was the person's complexion like?",
        cards=_cards(
            "skin",
            [
                ("fair", "Fair"),
                ("wheatish", "Wheatish"),
                ("medium_brown", "Medium brown"),
                ("dark_brown", "Dark brown"),
            ],
        ),
        sketch_feature="skin",
        value_keywords={
            "fair": ("fair", "light skin", "pale"),
            "wheatish": ("wheatish", "wheat"),
            "dark_brown": ("dark", "dusky"),
            "medium_brown": ("brown", "medium"),
        },
    ),
    # ---- face -------------------------------------------------------------------------
    FieldDef(
        "face_shape",
        "face",
        "Face shape",
        "Overall face shape",
        "What was the overall shape of the person's face?",
        cards=_cards(
            "face",
            [
                ("oval", "Oval"),
                ("round", "Round"),
                ("square", "Square"),
                ("long", "Long"),
                ("heart", "Heart"),
                ("diamond", "Diamond"),
            ],
        ),
        sketch_feature="face_shape",
        value_keywords={
            "long": ("long face", "face was long", "oblong"),
            "round": ("round face", "face was round"),
            "square": ("square face", "square"),
            "oval": ("oval",),
        },
    ),
    FieldDef(
        "hair",
        "face",
        "Hair",
        "Hair length, style and colour",
        "What do you remember about the person's hair?",
        cards=_cards(
            "hair",
            [
                ("short_straight", "Short straight"),
                ("short_curly", "Short curly"),
                ("medium", "Medium length"),
                ("long", "Long"),
                ("bald", "Bald"),
                ("receding", "Receding"),
            ],
        ),
        sketch_feature="hair",
        value_keywords={
            "short": ("short hair", "hair short", "cropped"),
            "long": ("long hair", "hair long"),
            "bald": ("bald",),
            "curly": ("curly",),
            "grey": ("grey", "gray", "white hair"),
        },
    ),
    FieldDef(
        "eyes",
        "face",
        "Eyes",
        "Eye size, shape and anything notable",
        "What do you remember about the person's eyes?",
        cards=_cards(
            "eyes",
            [
                ("large", "Large"),
                ("small", "Small"),
                ("narrow", "Narrow"),
                ("round", "Round"),
                ("deep_set", "Deep set"),
                ("hooded", "Hooded"),
            ],
        ),
        sketch_feature="eyes",
        value_keywords={
            "large": ("large eyes", "big eyes", "eyes were large", "eyes were big"),
            "small": ("small eyes", "eyes were small"),
            "narrow": ("narrow eyes",),
            "round": ("round eyes",),
            "deep_set": ("deep set", "deep-set", "sunken"),
        },
    ),
    FieldDef(
        "brows",
        "face",
        "Eyebrows",
        "Eyebrow thickness and shape",
        "What do you remember about the person's eyebrows?",
        cards=_cards(
            "brows",
            [
                ("thick", "Thick"),
                ("thin", "Thin"),
                ("arched", "Arched"),
                ("straight", "Straight"),
                ("joined", "Joined"),
            ],
        ),
        sketch_feature="brows",
        value_keywords={
            "thick": ("thick eyebrows", "thick brows", "bushy"),
            "thin": ("thin eyebrows", "thin brows"),
            "joined": ("joined", "unibrow"),
            "arched": ("arched",),
        },
    ),
    FieldDef(
        "nose",
        "face",
        "Nose",
        "Nose shape and size",
        "What do you remember about the person's nose?",
        cards=_cards(
            "nose",
            [
                ("straight", "Straight"),
                ("broad", "Broad"),
                ("hooked", "Hooked"),
                ("small", "Small"),
                ("long", "Long"),
                ("flat", "Flat"),
                ("upturned", "Upturned"),
            ],
        ),
        sketch_feature="nose",
        value_keywords={
            "long": ("long nose", "nose was long"),
            "broad": ("broad nose", "wide nose", "flat nose"),
            "hooked": ("hooked", "beak"),
            "small": ("small nose",),
            "straight": ("straight nose", "sharp nose"),
        },
    ),
    FieldDef(
        "mouth",
        "face",
        "Mouth and lips",
        "Mouth width and lip fullness",
        "What do you remember about the person's mouth or lips?",
        cards=_cards(
            "mouth",
            [
                ("wide", "Wide"),
                ("small", "Small"),
                ("full_lips", "Full lips"),
                ("thin_lips", "Thin lips"),
            ],
        ),
        sketch_feature="mouth",
        value_keywords={
            "thin_lips": ("thin lips", "lips were thin"),
            "full_lips": ("full lips", "thick lips"),
            "wide": ("wide mouth",),
            "small": ("small mouth",),
        },
    ),
    FieldDef(
        "jaw",
        "face",
        "Jaw and chin",
        "Jaw width and chin shape",
        "What do you remember about the person's jaw or chin?",
        cards=_cards(
            "jaw",
            [
                ("square", "Square"),
                ("round", "Round"),
                ("pointed", "Pointed"),
                ("wide", "Wide"),
                ("narrow", "Narrow"),
            ],
        ),
        sketch_feature="jaw",
        value_keywords={
            "wide": ("wide jaw", "broad jaw", "jaw was wide"),
            "square": ("square jaw",),
            "pointed": ("pointed chin", "pointed jaw"),
            "narrow": ("narrow jaw",),
            "round": ("round jaw", "round chin"),
        },
    ),
    FieldDef(
        "ears",
        "face",
        "Ears",
        "Ear size and whether they stick out",
        "What do you remember about the person's ears?",
        cards=_cards(
            "ears",
            [
                ("normal", "Nothing notable"),
                ("large", "Large"),
                ("protruding", "Sticking out"),
                ("small", "Small"),
            ],
        ),
        sketch_feature="ears",
        value_keywords={
            "large": ("large ears", "big ears"),
            "protruding": ("sticking out", "protruding"),
            "small": ("small ears",),
        },
    ),
    FieldDef(
        "facial_hair",
        "face",
        "Facial hair",
        "Beard, moustache, stubble or clean shaven",
        "What do you remember about the person's facial hair, if any?",
        cards=_cards(
            "facial_hair",
            [
                ("none", "Clean shaven"),
                ("stubble", "Stubble"),
                ("moustache", "Moustache"),
                ("goatee", "Goatee"),
                ("full_beard", "Full beard"),
            ],
        ),
        sketch_feature="hair",
        value_keywords={
            "none": ("no beard", "clean shaven", "clean-shaven"),
            "moustache": ("moustache", "mustache"),
            "full_beard": ("beard",),
            "stubble": ("stubble",),
            "goatee": ("goatee",),
        },
    ),
    # ---- marks + accessories ----------------------------------------------------------
    FieldDef(
        "scars",
        "marks",
        "Scars",
        "Any scars, with position",
        "Did you notice any marks on the person's face? Describe anything you remember.",
        cards=_cards("scars", [("none", "None noticed")]),
        sketch_feature="marks",
        value_keywords={"scar": ("scar",)},
    ),
    FieldDef(
        "moles",
        "marks",
        "Moles",
        "Any moles or spots, with position",
        "What else do you remember about the person's skin?",
        cards=_cards("moles", [("none", "None noticed")]),
        sketch_feature="marks",
        value_keywords={"mole": ("mole",)},
    ),
    FieldDef(
        "tattoos",
        "marks",
        "Tattoos",
        "Any visible tattoos",
        "What do you remember about any tattoos or markings?",
        cards=_cards("tattoos", [("none", "None noticed")]),
        value_keywords={"tattoo": ("tattoo",)},
    ),
    FieldDef(
        "other_marks",
        "marks",
        "Other marks",
        "Anything else distinctive about the face",
        "Was there anything else distinctive about the person's appearance?",
        sketch_feature="marks",
    ),
    FieldDef(
        "headwear",
        "marks",
        "Headwear",
        "Cap, turban, helmet or nothing",
        "What, if anything, was the person wearing on their head?",
        cards=_cards(
            "headwear",
            [
                ("none", "Nothing"),
                ("cap", "Cap"),
                ("turban", "Turban"),
                ("helmet", "Helmet"),
                ("hood", "Hood"),
            ],
        ),
        value_keywords={
            "cap": ("cap", "hat"),
            "turban": ("turban", "pagdi"),
            "helmet": ("helmet",),
        },
    ),
    FieldDef(
        "eyewear",
        "marks",
        "Eyewear",
        "Spectacles, sunglasses or nothing",
        "Was the person wearing anything over their eyes?",
        cards=_cards(
            "eyewear",
            [("none", "Nothing"), ("spectacles", "Spectacles"), ("sunglasses", "Sunglasses")],
        ),
        value_keywords={
            "spectacles": ("spectacles", "glasses", "specs"),
            "sunglasses": ("sunglasses", "goggles"),
        },
    ),
    FieldDef(
        "face_cover",
        "marks",
        "Face covering",
        "Mask, cloth or nothing",
        "Was any part of the person's face covered?",
        cards=_cards(
            "face_cover",
            [
                ("none", "Nothing"),
                ("mask", "Mask"),
                ("cloth", "Cloth"),
                ("partial", "Partly covered"),
            ],
        ),
        value_keywords={"mask": ("mask",), "cloth": ("cloth", "handkerchief", "scarf")},
    ),
    FieldDef(
        "clothing",
        "marks",
        "Clothing",
        "Clothing and colours",
        "What do you remember about the person's clothing?",
        value_keywords={
            "shirt": ("shirt",),
            "kurta": ("kurta",),
            "jacket": ("jacket",),
            "t_shirt": ("t-shirt", "tshirt"),
        },
    ),
    # ---- scene (extracted, not asked) ---------------------------------------------------
    FieldDef(
        "place_type",
        "scene",
        "Place",
        "Type of place (shop, room, street, junction)",
        "",
        asked=False,
        value_keywords={
            "shop": ("shop", "store", "counter"),
            "room": ("room", "house", "flat"),
            "street": ("street", "road", "lane"),
            "junction": ("junction", "crossing", "circle"),
        },
    ),
    FieldDef(
        "layout_notes", "scene", "Layout", "Notes about the layout of the place", "", asked=False
    ),
    FieldDef(
        "objects",
        "scene",
        "Objects",
        "Objects mentioned (counter, table, vehicle...)",
        "",
        asked=False,
    ),
    FieldDef("people_positions", "scene", "People", "Where people were", "", asked=False),
    FieldDef("evidence", "scene", "Evidence", "Items left, taken or dropped", "", asked=False),
    FieldDef("events", "scene", "Events", "Sequence of events in order", "", asked=False),
]

FIELD_MAP: dict[str, FieldDef] = {f.key: f for f in FIELDS}
ASKED_FIELDS: list[FieldDef] = [f for f in FIELDS if f.asked]
CARD_CATALOG: dict[str, dict[str, str]] = {
    c.id: {"id": c.id, "label": c.label, "field": f.key, "value": c.value}
    for f in FIELDS
    for c in f.cards
}

# Per-field value keywords used by the leading-question rule check (section 9).
LEADING_VALUE_KEYWORDS: dict[str, tuple[str, ...]] = {
    f.key: tuple(sorted({kw.strip() for kws in f.value_keywords.values() for kw in kws}))
    for f in FIELDS
}

# Contradiction checks for the "check" stage: (field_a, value_a_fragment, field_b,
# value_b_fragment, field_to_re_ask).
CONTRADICTIONS: list[tuple[str, str, str, str, str]] = [
    ("facial_hair", "none", "other_marks", "beard", "facial_hair"),
    ("gender", "female", "facial_hair", "beard", "gender"),
    ("gender", "female", "facial_hair", "moustache", "gender"),
    ("face_cover", "mask", "mouth", "", "mouth"),
    ("eyewear", "sunglasses", "eyes", "", "eyes"),
    ("hair", "bald", "headwear", "", "hair"),
]


def field_options(f: FieldDef) -> list[dict[str, str]]:
    opts = [dict(CARD_CATALOG[c.id]) for c in f.cards]
    opts.append(
        {"id": NOT_REMEMBERED, "label": "I don't remember", "field": f.key, "value": NOT_REMEMBERED}
    )
    return opts


def empty_sheet() -> dict[str, dict[str, object]]:
    return {}


def filled(sheet: dict[str, dict[str, object]], key: str) -> bool:
    entry = sheet.get(key)
    if not entry:
        return False
    v = entry.get("value")
    return bool(v) and str(v).strip() != ""
