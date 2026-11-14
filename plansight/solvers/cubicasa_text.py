"""CubiCasa room-label count solver based on cached OCR."""
from __future__ import annotations

import re
import unicodedata

from plansight.config import resolve
from plansight.ocr import OCRToken, read_text
from plansight.types import Answer, Evidence


_TEMPLATES = {
    "sauna": ("sauna", "saunaa"),
    "kitchen": ("kitchen", "keittio", "keittokomer", "tupakeitti", "apukeitti"),
    "bedroom": ("bedroom", "makuuhuone", "makuuhuonetta"),
    "bathroom": ("bathroom", "washroom", "kylpy- tai pesuhuone", "kylpyhuone", "pesuhuone"),
    "wc_room": ("separate wc room", "erillista wc", "wc-tilaa", "wc-tiloja"),
    "balcony": ("balcon", "parveke", "parveketta"),
}

_LABEL_PATTERNS = {
    "sauna": re.compile(r"^(?:S|SAUNA)[0-9]*$"),
    "kitchen": re.compile(r"^(?:KK|TK|K|KEITTIO|KEITTOKOMERO|TUPAK|TUPAKEITTIO|APUKEITTIO)[0-9]*$"),
    "bedroom": re.compile(r"^(?:MH(?:[0-9]+|[A-Z])?|MAKUUH)$"),
    "bathroom": re.compile(r"^(?:KPH|KH|PH|PESUH|PESUHUONE|SH|GH|PE)[0-9]*$"),
    "wc_room": re.compile(r"^WC(?:[0-9]+|[A-Z])?$"),
    "balcony": re.compile(r"^(?:PARV[0-9]*|PARVEKE|LASITETTUPARVEKE)$"),
}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _template(question: str) -> str | None:
    folded = _fold(question)
    if any(cue in folded for cue in ("sink", "wash basin", "tiskiallas", "tiskiallasta")):
        return None
    if ("not counting separate wc" in folded or "separate wc rooms are excluded" in folded
            or ("kylpy-" in folded and "lukuun ottamatta" in folded)):
        return "bathroom"
    matches = [key for key, cues in _TEMPLATES.items() if any(_fold(cue) in folded for cue in cues)]
    # Questions about drawn toilet bowls are a different visual template.
    return matches[0] if len(matches) == 1 else None


def _canonical(token: str) -> str:
    value = _fold(token).upper()
    value = re.sub(r"[^A-Z0-9]", "", value)
    # OCR often reads the C in the compact room label WC as a zero.
    if value == "W0":
        return "WC"
    return value


def _matches(token: OCRToken, template: str) -> bool:
    pattern = _LABEL_PATTERNS[template]
    # Floor-plan summaries such as "2H+KK+S" contain multiple room labels.
    parts = re.split(r"[+/]", token.text)
    return any(pattern.fullmatch(_canonical(part)) for part in parts)


def _any_room_label(tokens: list[OCRToken]) -> bool:
    return any(token.confidence >= 0.25 and _matches(token, kind)
               for token in tokens for kind in _LABEL_PATTERNS)


class CubicasaTextSolver:
    name = "cubicasa_text"

    def can_handle(self, path: str) -> bool:
        return path.replace("\\", "/").startswith("data/cubicasa5k/") and path.lower().endswith(".png")

    def solve(self, path: str, question: str) -> Answer | None:
        template = _template(question)
        if template is None or not self.can_handle(path):
            return None
        try:
            tokens = read_text(resolve(path))
        except Exception:  # corrupt/missing drawings or OCR runtime failures are abstentions
            return None

        if not tokens or max((token.confidence for token in tokens), default=0.0) < 0.15:
            return None
        # A blank sheet or title-block-only OCR cannot support a zero room count.
        if not _any_room_label(tokens):
            return None
        candidates = [token for token in tokens if _matches(token, template)]
        # An ambiguous label can change the count, so abstain instead of silently dropping it.
        if any(token.confidence < 0.25 for token in candidates):
            return None
        evidence = [Evidence(file=path, page=0, bbox=token.bbox, label=token.text) for token in candidates]
        return Answer(
            value=len(evidence), unit="count", evidence=evidence, method="deterministic",
            confidence=0.8 if candidates else 0.65,
            explanation=f"Counted {template} room labels recognized by OCR.",
        )
