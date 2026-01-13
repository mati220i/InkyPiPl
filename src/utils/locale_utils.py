import json
import os

import logging

_LOCALES = {}

logger = logging.getLogger(__name__)

def load_locale(lang):
    path = os.path.join(os.environ.get("PROJECT_DIR"), "src", "locales", f"{lang}.json")
    logger.info(f"Loaded locale from path: {path}")
    with open(path, "r", encoding="utf-8") as f:
        _LOCALES[lang] = json.load(f)

def t(key, lang="en", **kwargs):
    if lang not in _LOCALES:
        load_locale(lang)
    text = _LOCALES[lang].get(key, key)
    return text.format(**kwargs)
