import ast
import string
from pathlib import Path

import pytest

from evekonta import i18n, reports

SRC = Path(__file__).resolve().parent.parent / "evekonta"


def tr_texts() -> set[str]:
    """Every literal text passed to tr() in the app code."""
    found = set()
    for path in SRC.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "tr" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
    # texts picked at runtime from tables
    found.update(reports.ACTIVITIES.values())
    found.update(("URGENT", "SOON", "INFO", "Job"))
    return found


def fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.fixture(autouse=True)
def english_after():
    yield
    i18n.set_language("en")


def test_english_is_default():
    assert i18n.DEFAULT_LANGUAGE == "en"
    assert i18n.get_language() == "en"
    assert i18n.tr("Alerts") == "Alerts"
    assert i18n.tr("{n} accounts", n=3) == "3 accounts"


def test_polish_translation():
    i18n.set_language("pl")
    assert i18n.tr("Alerts") == "Uwagi"
    assert i18n.tr("{n} accounts", n=3) == "3 kont"
    assert i18n.tr("not translated text") == "not translated text"


def test_unknown_language_falls_back_to_english():
    i18n.set_language("de")
    assert i18n.get_language() == "en"


def test_every_text_has_polish_translation():
    missing = sorted(tr_texts() - set(i18n.PL))
    assert missing == []


def test_translations_keep_placeholders():
    for en, pl in i18n.PL.items():
        assert fields(en) == fields(pl), en

