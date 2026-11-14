"""Tiny cue-word language tagger for routing stats (not used for routing decisions)."""
from __future__ import annotations

import re

_CUES = {
    "en": {"how", "many", "what", "is", "the", "are", "there", "of", "this", "on", "in", "floor", "plan"},
    "de": {"wie", "viele", "gibt", "es", "dem", "der", "die", "das", "diesem", "auf", "ist", "gross", "groß", "sind", "im", "enthält"},
    "fr": {"combien", "de", "quelle", "est", "la", "le", "sur", "ce", "plan", "pièces", "cet", "étage", "y", "a-t-il", "en"},
    "it": {"quanti", "quante", "qual", "è", "il", "la", "di", "in", "questa", "questo", "pianta", "piano", "sono", "ci", "del", "nel"},
    "fi": {"kuinka", "monta", "on", "pohjapiirustuksessa", "mikä", "kerroksen", "kerroksessa", "mallissa", "pohjapiirustukseen"},
    "da": {"hvor", "mange", "er", "der", "i", "modellen", "på", "hvad", "plantegningen", "etagen"},
    "et": {"mitu", "on", "mudelis", "milline", "korruse", "plaanil", "ruumi", "kui", "suur"},
    "nl": {"hoeveel", "bevat", "het", "model", "wat", "is", "de", "van", "op", "plattegrond", "zijn", "er"},
    "es": {"cuál", "es", "el", "número", "de", "en", "modelo", "la", "cuántos", "cuántas", "planta"},
    "sv": {"hur", "många", "finns", "det", "i", "modellen", "vad", "är", "på", "planritningen"},
    "no": {"hvor", "mange", "er", "det", "i", "modellen", "hva", "på", "plantegningen"},
    "pt": {"quantos", "quantas", "qual", "é", "o", "a", "no", "na", "modelo", "planta"},
    "pl": {"ile", "jest", "w", "modelu", "na", "rzucie", "jaka"},
    "ro": {"câte", "câți", "care", "este", "în", "modelul", "pe", "planul"},
    "cs": {"kolik", "je", "v", "modelu", "na", "půdorysu", "jaká"},
}


def detect(q: str) -> str:
    words = re.findall(r"[\w'-]+", re.sub(r"«[^»]*»|'[^']*'|„[^“”]*[“”]|\"[^\"]*\"", " ", q.casefold()))
    if not words:
        return "other"
    scores = {lang: sum(w in cues for w in words) for lang, cues in _CUES.items()}
    lang, s = max(scores.items(), key=lambda kv: kv[1])
    return lang if s else "other"
