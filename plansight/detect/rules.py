"""How CubiCasa annotations map to the 12 question kinds. Fitted against all 85k Junction gold answers
(scripts/fit_cubicasa_rules.py): every rule below reproduces the gold count on >= 98.5% of plans (most at 100%).

Objects (detector model 1): count = number of detections of the listed classes.
Rooms (detector model 2): a room's category comes from the annotator's Finnish name label; saunas are rooms of class
"Space Sauna" or rooms that contain a sauna stove.
"""
from __future__ import annotations

import re
import unicodedata

# question kind -> detector classes whose detections are summed (model 1)
OBJECT_KINDS = {
    "window": ("window",),
    "door": ("door",),                 # "Door None" (open doorway, no leaf) is class "opening" and NOT counted
    "toilet": ("toilet",),
    "sink": ("sink", "double_sink"),   # a double sink counts once
    "shower_bath": ("shower", "bathtub"),  # ShowerCab is a separate class and NOT counted
}

ROOM_LABELS = {
    "bedroom": re.compile(r"^(?:MH(?:[0-9]+|[A-Z])?|MAKUUH)$"),
    "kitchen": re.compile(r"^(?:KK|K|KEITTIO|KEITTOKOMERO|TUPAK|TUPAKEITTIO|APUKEITTIO|APUK|AVOK|AVOKEITTIO)[0-9]*$"),
    "bathroom": re.compile(r"^(?:KPH|KH|PH|PESUH|PESUHUONE|SH|GH|PE|PSH|PESU)[0-9]*$"),
    "wc_room": re.compile(r"^WC(?:[0-9]+|[A-Z])?$"),
    "balcony": re.compile(r"^(?:PARV[0-9]*|PARVEKE|LASITETTUPARVEKE)$"),
}
ROOM_KINDS = ("bedroom", "kitchen", "bathroom", "wc_room", "sauna", "balcony")


def norm(t: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().upper())


def tokens(text: str) -> list[str]:
    return [n for x in re.split(r"[\s/+,&-]+", text or "") if (n := norm(x))]


def room_kinds(text: str) -> set[str]:
    """Categories a room label belongs to ("KH/WC" -> {bathroom, wc_room})."""
    ts = tokens(text)
    return {k for k, pat in ROOM_LABELS.items() if any(pat.match(t) for t in ts)}
