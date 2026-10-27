import re
from pathlib import Path

import pytest

from zugup.i18n import CATALOGS, LANGUAGES, translator
from zugup.locales import en, fr

SRC = Path(__file__).resolve().parent.parent / "src" / "zugup"
PLACEHOLDER = re.compile(r"\{(\w+)\}")
TEMPLATE_KEY = re.compile(r"""\bt\(\s*'([\w.]+)'""")
CLIENT_KEY = re.compile(r"""\bt\(\s*["'`]([\w.]+)["'`]""")
PYTHON_KEY = re.compile(r"""\bt\(\s*f?["']([\w.]+)["']""")


def known(key):
    return any(key in messages or f"{key}.one" in messages for messages in (fr.MESSAGES, en.MESSAGES))


def test_catalogs_have_the_same_keys():
    assert set(fr.MESSAGES) == set(en.MESSAGES)


def test_catalogs_use_the_same_placeholders():
    for key in fr.MESSAGES:
        if isinstance(fr.MESSAGES[key], str):
            assert set(PLACEHOLDER.findall(fr.MESSAGES[key])) == set(PLACEHOLDER.findall(en.MESSAGES[key])), key


def test_list_entries_have_the_same_length():
    for key, value in fr.MESSAGES.items():
        if isinstance(value, list):
            assert len(value) == len(en.MESSAGES[key]), key


def test_every_plural_has_both_forms():
    for messages in CATALOGS.values():
        for key in messages:
            if key.endswith(".one"):
                assert key[:-4] + ".other" in messages


def test_every_key_used_by_templates_scripts_and_python_exists():
    sources = [
        (TEMPLATE_KEY, SRC / "web" / "templates", "*.html"),
        (CLIENT_KEY, SRC / "web" / "static", "*.js"),
        (PYTHON_KEY, SRC / "coach", "*.py"),
    ]
    missing = []
    for pattern, folder, glob in sources:
        for path in folder.glob(glob):
            for key in pattern.findall(path.read_text()):
                if not key.endswith(".") and not known(key):
                    missing.append((path.name, key))
    assert missing == []


def test_translator_picks_the_plural_form_and_formats_parameters():
    t = translator("en")
    assert t("js.games", count=1) == "1 game" and t("js.games", count=3) == "3 games"
    assert translator("fr")("js.games", count=0) == "0 parties"


def test_numbers_follow_the_language():
    assert translator("fr").percent(12.5) == "12,5 %" and translator("en").percent(12.5) == "12.5%"
    assert translator("fr").percent(80, 0) == "80 %" and translator("en").percent(80, 0) == "80%"


def test_unknown_language_falls_back_to_french():
    assert translator("de").lang == "fr" and set(LANGUAGES) == set(CATALOGS)


def test_client_messages_only_hold_script_keys():
    assert translator("en").client_messages() and all(k.startswith("js.") for k in translator("en").client_messages())


def test_english_advice_and_plan_texts():
    from zugup.coach.advice import generate_advice
    axes = [{"key": "endgame", "score": 80, "peer_score": 90}, {"key": "opening", "score": 95, "peer_score": 90}]
    text = generate_advice({
        "speed": "blitz", "games": 40, "serious_rate": 0.125, "axes": axes,
        "branch": {"line": "1. e4 e5", "color": "black", "games": 10, "errors": 8, "rate": 0.8, "baseline": 0.5},
    }, translator("en"))
    assert "over 40 analyzed games, 12.5% of your moves" in text
    assert "Area to work on: Endgame (80.0%, versus 90.0% for opponents at your level)." in text
    assert "Strength: Opening" in text and "Line to review with Black: 1. e4 e5." in text
