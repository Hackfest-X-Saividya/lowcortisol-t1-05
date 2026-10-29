"""Safe, open, non-leading interview questions in Kannada, Hindi and English.

Used when the LLM is unavailable (mock mode), when its question fails the leading check, or
when it asked about a different field than the deterministic engine chose.
"""

from __future__ import annotations

from app.services.interview.fields import FIELD_MAP

SITUATION: dict[str, dict[str, str]] = {
    "witness_position": {
        "kn": "ಆ ವ್ಯಕ್ತಿಯನ್ನು ನೋಡಿದಾಗ ನೀವು ಎಲ್ಲಿದ್ದಿರಿ?",
        "hi": "जब आपने उस व्यक्ति को देखा, आप कहाँ थे?",
        "en": "Where were you when you saw the person?",
    },
    "lighting": {
        "kn": "ಆ ಸಮಯದಲ್ಲಿ ಬೆಳಕು ಹೇಗಿತ್ತು?",
        "hi": "उस समय रोशनी कैसी थी?",
        "en": "What was the light like at that time?",
    },
    "distance_m": {
        "kn": "ಆ ವ್ಯಕ್ತಿ ನಿಮ್ಮಿಂದ ಎಷ್ಟು ದೂರದಲ್ಲಿದ್ದರು?",
        "hi": "वह व्यक्ति आपसे कितनी दूर था?",
        "en": "How far away from you was the person?",
    },
    "view_duration": {
        "kn": "ಆ ವ್ಯಕ್ತಿಯನ್ನು ಎಷ್ಟು ಹೊತ್ತು ನೋಡಿದಿರಿ?",
        "hi": "आपने उस व्यक्ति को कितनी देर देखा?",
        "en": "For how long could you see the person?",
    },
    "view_angle": {
        "kn": "ಆ ವ್ಯಕ್ತಿಯ ಮುಖವನ್ನು ಯಾವ ಕಡೆಯಿಂದ ನೋಡಿದಿರಿ?",
        "hi": "आपने उसका चेहरा किस तरफ़ से देखा?",
        "en": "From which side did you see the person's face?",
    },
    "gender": {
        "kn": "ಆ ವ್ಯಕ್ತಿಯನ್ನು ಒಟ್ಟಾರೆ ಹೇಗೆ ವಿವರಿಸುತ್ತೀರಿ?",
        "hi": "आप उस व्यक्ति का कुल मिलाकर वर्णन कैसे करेंगे?",
        "en": "How would you describe the person overall?",
    },
    "age_range": {
        "kn": "ಆ ವ್ಯಕ್ತಿಗೆ ಸುಮಾರು ಎಷ್ಟು ವಯಸ್ಸು ಇರಬಹುದು?",
        "hi": "उस व्यक्ति की उम्र लगभग कितनी रही होगी?",
        "en": "About how old did the person seem?",
    },
    "height_relative": {
        "kn": "ನಿಮಗೆ ಹೋಲಿಸಿದರೆ ಆ ವ್ಯಕ್ತಿ ಎಷ್ಟು ಎತ್ತರವಿದ್ದರು?",
        "hi": "आपकी तुलना में वह व्यक्ति कितना लंबा था?",
        "en": "How tall was the person compared with you?",
    },
    "build": {
        "kn": "ಆ ವ್ಯಕ್ತಿಯ ಮೈಕಟ್ಟು ಹೇಗಿತ್ತು?",
        "hi": "उस व्यक्ति की कद-काठी कैसी थी?",
        "en": "What was the person's build like?",
    },
    "skin_tone": {
        "kn": "ಆ ವ್ಯಕ್ತಿಯ ಮೈಬಣ್ಣ ಹೇಗಿತ್ತು?",
        "hi": "उस व्यक्ति का रंग कैसा था?",
        "en": "What was the person's complexion like?",
    },
}

LABELS: dict[str, dict[str, str]] = {
    "face_shape": {"kn": "ಮುಖದ ಆಕಾರ", "hi": "चेहरे के आकार", "en": "face shape"},
    "hair": {"kn": "ಕೂದಲು", "hi": "बालों", "en": "hair"},
    "eyes": {"kn": "ಕಣ್ಣುಗಳು", "hi": "आँखों", "en": "eyes"},
    "brows": {"kn": "ಹುಬ್ಬುಗಳು", "hi": "भौंहों", "en": "eyebrows"},
    "nose": {"kn": "ಮೂಗು", "hi": "नाक", "en": "nose"},
    "mouth": {"kn": "ಬಾಯಿ ಮತ್ತು ತುಟಿಗಳು", "hi": "मुँह और होंठों", "en": "mouth and lips"},
    "jaw": {"kn": "ದವಡೆ ಮತ್ತು ಗಲ್ಲ", "hi": "जबड़े और ठोड़ी", "en": "jaw and chin"},
    "ears": {"kn": "ಕಿವಿಗಳು", "hi": "कानों", "en": "ears"},
    "facial_hair": {"kn": "ಗಡ್ಡ ಅಥವಾ ಮೀಸೆ", "hi": "दाढ़ी या मूँछ", "en": "facial hair"},
    "scars": {"kn": "ಮುಖದ ಮೇಲಿನ ಗುರುತುಗಳು", "hi": "चेहरे के निशानों", "en": "any marks on the face"},
    "moles": {"kn": "ಚರ್ಮ", "hi": "त्वचा", "en": "skin"},
    "tattoos": {"kn": "ಹಚ್ಚೆ", "hi": "टैटू", "en": "tattoos"},
    "other_marks": {
        "kn": "ಬೇರೆ ಯಾವುದೇ ವಿಶೇಷತೆ",
        "hi": "किसी और खास बात",
        "en": "anything else distinctive",
    },
    "headwear": {"kn": "ತಲೆಯ ಮೇಲೆ ಧರಿಸಿದ್ದು", "hi": "सिर पर पहनी चीज़", "en": "anything on the head"},
    "eyewear": {"kn": "ಕಣ್ಣಿನ ಮೇಲೆ ಧರಿಸಿದ್ದು", "hi": "आँखों पर पहनी चीज़", "en": "anything over the eyes"},
    "face_cover": {"kn": "ಮುಖ ಮುಚ್ಚಿದ್ದು", "hi": "चेहरा ढकने", "en": "anything covering the face"},
    "clothing": {"kn": "ಬಟ್ಟೆ", "hi": "कपड़ों", "en": "clothing"},
}

PATTERN = {
    "kn": "ಆ ವ್ಯಕ್ತಿಯ {label} ಬಗ್ಗೆ ನಿಮಗೆ ಏನು ನೆನಪಿದೆ?",
    "hi": "उस व्यक्ति के {label} के बारे में आपको क्या याद है?",
    "en": "What do you remember about the person's {label}?",
}

# Asked when the open gender question got no usable answer (often the speech recognition
# garbled it). No sketch is drawn without it, so it is asked again, simply, with both choices
# named equally; the witness can also tap Man / Woman / I don't remember.
GENDER_RETRY = {
    "kn": "ಆ ವ್ಯಕ್ತಿ ಗಂಡಸೋ ಹೆಂಗಸೋ?",
    "hi": "वह व्यक्ति आदमी था या औरत?",
    "en": "Was the person a man or a woman?",
}

ACK = {"kn": "ಸರಿ.", "hi": "ठीक है।", "en": "Thank you."}
UPDATED = {
    "kn": "ಸರಿ, ಚಿತ್ರವನ್ನು ಬದಲಿಸಿದೆ.",
    "hi": "ठीक है, चित्र बदल दिया।",
    "en": "Done, I have changed the sketch.",
}
REVIEW = {
    "kn": "ಚಿತ್ರವನ್ನು ನೋಡಿ. ಆ ವ್ಯಕ್ತಿಗಿಂತ ಏನಾದರೂ ಬೇರೆಯಾಗಿ ಕಾಣುತ್ತಿದೆಯೇ? ಹೇಳಿ, ನಾನು ಬದಲಿಸುತ್ತೇನೆ.",
    "hi": "चित्र देखिए। क्या कुछ उस व्यक्ति से अलग लग रहा है? बताइए, मैं बदल दूँगा।",
    "en": "Look at the sketch. Does anything look different from the person? Tell me and I will change it.",
}
OPENING = {
    "kn": "ನೀವು ನೋಡಿದ ವ್ಯಕ್ತಿಯ ಬಗ್ಗೆ ನಿಮಗೆ ನೆನಪಿರುವುದನ್ನೆಲ್ಲಾ ನಿಮ್ಮದೇ ಮಾತುಗಳಲ್ಲಿ ಹೇಳಿ.",
    "hi": "आपने जिस व्यक्ति को देखा, उसके बारे में जो कुछ याद है, अपने शब्दों में बताइए।",
    "en": "Tell me everything you remember about the person you saw, in your own words.",
}


def question_for(field_key: str, lang: str) -> str:
    lang = lang if lang in ("kn", "hi", "en") else "en"
    if field_key in SITUATION:
        return SITUATION[field_key][lang]
    label = LABELS.get(field_key, {}).get(lang)
    if not label:
        f = FIELD_MAP.get(field_key)
        label = f.label.lower() if f else field_key
    return PATTERN[lang].format(label=label)


def line(table: dict[str, str], lang: str) -> str:
    return table.get(lang) or table["en"]
