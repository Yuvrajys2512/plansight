"""English parsers per domain: the ground truth the multilingual router is mined from and scored against.

A route is (template, params). Slot values (room names/numbers, apartment letters, storey and model names)
are kept verbatim as they appear in the question.
"""
from __future__ import annotations

import re

from plansight.config import source_of

DOMAINS = {"swiss_dwellings": "swiss", "ifc_models": "ifc", "cubicasa5k": "cubicasa"}

# params copied verbatim from the question text (everything else, e.g. `kind`, is a fixed enum)
SLOT_KEYS = ("name", "number", "letter", "storey", "room", "model")


def domain_of(path: str) -> str | None:
    return DOMAINS.get(source_of(path))


# ------------------------------------------------------------------ cubicasa (no slots, 12 count templates)
CUBICASA_KINDS = ("window", "floor", "toilet", "sink", "shower_bath", "door",
                  "sauna", "kitchen", "bedroom", "bathroom", "wc_room", "balcony")
_CUBICASA_EN = [
    (r"how many windows\b", "window"),
    (r"how many (floors|storeys)\b", "floor"),
    (r"how many toilet bowls\b", "toilet"),
    (r"how many (sinks|wash ?basins)\b", "sink"),
    (r"how many showers and bathtubs\b", "shower_bath"),
    (r"how many doors\b", "door"),
    (r"how many saunas\b", "sauna"),
    (r"how many kitchens\b", "kitchen"),
    (r"how many bedrooms\b", "bedroom"),
    (r"how many (bathrooms|washrooms)\b", "bathroom"),
    (r"how many separate wc rooms\b", "wc_room"),
    (r"how many balconies\b", "balcony"),
]


def parse_cubicasa_en(q: str) -> tuple[str, dict] | None:
    for pat, kind in _CUBICASA_EN:
        if re.match(pat, q.strip(), re.I):
            return "count", {"kind": kind}
    return None


def parse_en(domain: str, q: str) -> tuple[str, dict] | None:
    if domain == "swiss":
        from plansight.solvers.swiss import parse_en as p
    elif domain == "ifc":
        from plansight.solvers.ifc import parse_en as p
    elif domain == "cubicasa":
        p = parse_cubicasa_en
    else:
        return None
    return p(q)


# ------------------------------------------------------------------ catalogue (for the Gemma prompt + validation)
CATALOG = {
    "swiss": {
        "count": {"kind": ["apartments", "doors", "windows", "toilets", "washbasins", "bathtubs", "showers"]},
        "count_rooms_named": {"name": "room label, verbatim"},
        "room_area": {"number": "room number, verbatim (e.g. 7.01)"},
        "apartment_area": {"letter": "apartment letter, verbatim (e.g. B)"},
        "total_area_named": {"name": "room label, verbatim"},
        "total_indoor_area": {},
    },
    "ifc": {
        "count": {"kind": ["doors", "windows", "rooms", "walls", "beams", "columns", "stairs", "sanitary", "lights"],
                  "model": "model name, verbatim (when the question is about the whole model)",
                  "storey": "storey name, verbatim (when the question is about one floor plan)"},
        "room_area": {"room": "room label, verbatim", "storey": "storey name, verbatim"},
        "total_room_area": {"storey": "storey name, verbatim"},
        "wall_length": {"storey": "storey name, verbatim"},
        "wall_side_area": {"storey": "storey name, verbatim"},
        "wall_volume": {"storey": "storey name, verbatim"},
        "slab_volume": {"storey": "storey name, verbatim"},
    },
    "cubicasa": {"count": {"kind": list(CUBICASA_KINDS)}},
}
