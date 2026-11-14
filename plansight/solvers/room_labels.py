"""Count rooms by reading their labels (multilingual lexicon over OCR tokens), every label an evidence box.

Frontier VLMs are good at this (they read "CHAMBRE 2", "Bed1", "M.BATH"); our symbol detectors are not, because a
bedroom is defined by its label, not by a drawn symbol. So bedrooms and toilet rooms are read, not detected.
AECV-Bench's gold rules: bedroom = a space labelled Bedroom/Chambre/Zimmer/Camera/...; toilet = each space labelled
WC/W.C./Bath/Bain/Douche/Shower/SDB/Bathroom/Toilet (lavatory excluded).
"""
from __future__ import annotations

import re
import unicodedata

# canonical form: casefolded, accents stripped, uppercase, only A-Z0-9 and CJK kept
BEDROOM = re.compile(
    r"^(?:(?:MASTER|MAIN|REAR|GUEST|KIDS?|CHILD(?:RE|RA)N'?S?|PARENTS?)?BED(?:ROOM)?(?:SUITE)?S?\d*[A-Z]?|"
    r"MBR\d*|BR\d+|BDRM\d*|CHAMBRE\d*|CHAMB\d*|CH\d+|"
    r"(?:SCHLAF|KINDER|GAST|ELTERN)ZIMMER\d*|ZIMMER\d*|CAMERA\d*|"
    r"DORMITORIO\d*|HABITACION\d*|RECAMARA\d*|QUARTO\d*|SLAAPKAMER\d*|SOVEROM\d*|SOVRUM\d*|"
    r"MH\d*|MAKUUHUONE\d*|SYPIALNIA\d*|POKOJ\d*|CHILDREN'?S?ROOM|PARENTS?ROOM)$"
)
BEDROOM_CJK = re.compile(r"卧|臥|寝室")
TOILET = re.compile(
    r"^(?:W\.?C\.?\d*|WC\d*|TOIL(?:ET(?:TE)?S?)?\.?\d*|M\.?BATH(?:ROOM)?\d*|(?:MASTER|MAIN|GUEST|EN)?BATH(?:ROOM)?S?\d*|"
    r"ENS(?:UITE)?|BAINS?\d*|SALLEDE?BAINS?\d*|SDB\d*|SALLED'?EAU\d*|SDE\d*|DOUCHE\d*|SHOWER(?:ROOM)?\d*|"
    r"BAGNO\d*|BADEZIMMER\d*|BAD\d*|BANO\d*|ASEO\d*|KPH|KH\d*|PH\d*|PESUH(?:UONE)?)$"
)
TOILET_CJK = re.compile(r"卫|衛|厕|廁|洗手间")


def canon(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.casefold())
    t = "".join(c for c in t if not unicodedata.combining(c)).upper()
    t = re.sub(r"[^A-Z0-9'.一-鿿]", "", t)
    return "WC" if t in ("W0", "WO", "W.0", "VC", "VVC") else t


def is_label(text: str, kind: str) -> bool:
    c = canon(text)
    if not c:
        return False
    if kind == "bedroom":
        return bool(BEDROOM.match(c) or BEDROOM_CJK.search(c))
    if kind == "toilet":
        return bool(TOILET.match(c) or TOILET_CJK.search(c))
    raise ValueError(kind)


def _near(a, b, gap: float) -> bool:
    return not (a[2] + gap < b[0] or b[2] + gap < a[0] or a[3] + gap < b[1] or b[3] + gap < a[1])


def find_labels(tokens, kind: str, min_conf: float = 0.5):
    """tokens: [(text, conf, (x0, y0, x1, y1))]. Returns [(text, bbox)] one per room (split words merged).

    Joins each token with its right-hand neighbour too, so "MASTER" + "BEDROOM" or "SALLE DE" + "BAINS" read as one.
    """
    toks = [(t, c, tuple(b)) for t, c, b in tokens if c >= min_conf and t.strip()]
    hits = []
    for t, c, b in toks:
        if is_label(t, kind):
            hits.append((t, b))
    # two-token labels on one line ("MASTER" "BEDROOM", "SALLE DE" "BAINS")
    for t, c, b in toks:
        h = b[3] - b[1]
        for t2, c2, b2 in toks:
            if b2 is b or not (0 <= b2[0] - b[2] <= 1.5 * h and abs(b2[1] - b[1]) < 0.5 * h):
                continue
            if is_label(t + t2, kind) and not is_label(t2, kind) and not is_label(t, kind):
                hits.append((f"{t} {t2}", (b[0], min(b[1], b2[1]), b2[2], max(b[3], b2[3]))))
    # one room can carry its label twice (OCR duplicates, "BEDROOM" + "BEDROOM2" over each other): merge overlaps
    out = []
    for t, b in hits:
        if not any(_near(b, o[1], 0) for o in out):
            out.append((t, b))
    return out
