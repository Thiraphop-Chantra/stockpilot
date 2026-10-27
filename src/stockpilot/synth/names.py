"""Random names for fictional customers, brands and suppliers.

Customer names join two generic Thai words (each with several common romanisations) and a
business form typical for the customer type, e.g. "shop + words" in Thai or "words + Shop" in
English. Brand and supplier names come from a hand-reviewed list of invented stems. Names are
never taken from real businesses; any resemblance is coincidental.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

import numpy as np

# Invented brand and company stems: every combination was reviewed by hand so that none forms a
# real word, a known name or anything offensive. Brands and suppliers share stems, as brand
# owners often carry their manufacturer's name.
_STEM_HEADS = (
    "Alv", "Bren", "Cal", "Dor", "Elv", "Fal", "Gav", "Hal", "Jor", "Kel", "Lor", "Mel",
    "Nor", "Orv", "Pal", "Quen", "Ral", "Sel", "Tal", "Ulv", "Vel", "Wyl", "Yor", "Zev",
)  # fmt: skip
_STEM_TAILS = ("ando", "ara", "eno", "ova", "ura", "orin", "ane")
BRAND_STEMS = tuple(
    head + tail
    for head in _STEM_HEADS
    for tail in _STEM_TAILS
    if not (tail == "ova" and head.endswith("v"))
)
SUPPLIER_FORMS = {
    "TH": ("{name} Industries Co., Ltd.", "{name} Manufacturing Co., Ltd."),
    "CN": ("{name} Industrial Co., Ltd.", "{name} Trading Co., Ltd."),
    "VN": ("{name} Joint Stock Company",),
    "MY": ("{name} Sdn. Bhd.",),
    "JP": ("{name} Corporation",),
    "ID": ("PT {name}",),
}


@cache
def vocabulary() -> dict:
    """The Thai word list, business forms and provinces (resources/th_words.json)."""
    text = files("stockpilot.synth").joinpath("resources/th_words.json").read_text("utf-8")
    return json.loads(text)


@dataclass(frozen=True)
class NameParts:
    """What a customer name is made of, so variants of the same name can be produced later."""

    ctype: str  # customer type, selects the business forms
    words: tuple[int, int]  # indices into name_words
    form: int  # index into the business forms of ctype


def random_parts(rng: np.random.Generator, ctype: str) -> NameParts:
    words = rng.choice(len(vocabulary()["name_words"]), size=2, replace=False)
    form = int(rng.integers(len(vocabulary()["business_forms"][ctype])))
    return NameParts(ctype, (int(words[0]), int(words[1])), form)


def thai_name(parts: NameParts) -> str:
    words = vocabulary()["name_words"]
    core = "".join(words[i]["th"] for i in parts.words)
    return vocabulary()["business_forms"][parts.ctype][parts.form]["th"].format(name=core)


def english_name(
    parts: NameParts, spelling: tuple[int, int] = (0, 0), joined: bool = False, suffix: int = 0
) -> str:
    """English spelling; ``spelling`` picks each word's romanisation, ``suffix`` the form text."""
    words = vocabulary()["name_words"]
    roman = [
        words[i]["en"][s % len(words[i]["en"])] for i, s in zip(parts.words, spelling, strict=True)
    ]
    core = (roman[0] + roman[1].lower()) if joined else f"{roman[0]} {roman[1]}"
    forms = vocabulary()["business_forms"][parts.ctype][parts.form]["en"]
    return forms[suffix % len(forms)].format(name=core)


def customer_name(rng: np.random.Generator, ctype: str, lang: str) -> tuple[str, NameParts]:
    parts = random_parts(rng, ctype)
    return (thai_name(parts) if lang == "th" else english_name(parts)), parts


def variant_name(rng: np.random.Generator, parts: NameParts, lang: str) -> tuple[str, str]:
    """A second spelling of the same customer, as typed by someone else.

    Thai originals get an English spelling; English originals get either the Thai spelling or a
    different romanisation. Returns ``(name, kind)`` with kind in
    ``th_to_en`` / ``en_to_th`` / ``romanization``.
    """
    if lang == "en" and rng.random() < 0.5:
        return thai_name(parts), "en_to_th"
    original = thai_name(parts) if lang == "th" else english_name(parts)
    kind = "th_to_en" if lang == "th" else "romanization"
    for _ in range(20):
        spelling = (int(rng.integers(3)), int(rng.integers(3)))
        name = english_name(parts, spelling, bool(rng.random() < 0.5), int(rng.integers(2)))
        if name != original and (kind == "th_to_en" or name != english_name(parts)):
            return name, kind
    return english_name(parts, (1, 1), joined=True, suffix=1), kind


def pick_stems(rng: np.random.Generator, n: int) -> list[str]:
    """``n`` distinct names built on the stems (numbered once every stem has been used)."""
    order = rng.permutation(len(BRAND_STEMS))
    size = len(BRAND_STEMS)
    return [
        BRAND_STEMS[order[k % size]] + ("" if k < size else f" {k // size + 1}") for k in range(n)
    ]


def supplier_name(rng: np.random.Generator, base: str, country: str) -> str:
    forms = SUPPLIER_FORMS[country]
    return forms[rng.integers(len(forms))].format(name=base)
