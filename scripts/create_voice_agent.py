"""Create (or update) the PlanSight voice agent on ElevenLabs and print its id.

Usage: .venv\\Scripts\\python.exe scripts/create_voice_agent.py
Writes ELEVENLABS_AGENT_ID=<id> into .env if it isn't there yet.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
KEY = os.environ["ELEVENLABS_API_KEY"]
API = "https://api.elevenlabs.io/v1/convai"
H = {"xi-api-key": KEY, "Content-Type": "application/json"}

PROMPT = """You are PlanSight, a voice assistant for construction site engineers. You talk like a calm, competent colleague on site:
short sentences, no filler, no markdown, no lists. Numbers are spoken naturally ("seven doors", "twelve point one square metres").

The engineer is looking at a construction drawing on screen. The current drawing is given in a context update (title and type).
For ANY question about the drawing (counts, areas, rooms, doors, windows, elements, schedules...), you MUST call the tool
ask_plansight with the question rephrased as one clear English question. Never answer from your own knowledge and never invent
a number. While the tool runs, say a very short filler like "Let me check the sheet."

The tool returns JSON with: value, unit, evidence_count, method, cost_usd, frontier_cost_usd, abstained, reason, explanation.
- Answer with the value first, then one short sentence on how you know (e.g. "I counted them with the detector and boxed each one on the sheet").
- If evidence_count > 0, say they're highlighted on the drawing so the engineer can check.
- Mention the cost only if asked, or briefly on the first answer ("that cost a fraction of a cent").
- If abstained is true, say honestly that you couldn't find solid evidence on this sheet and suggest what to check instead.

Reply in the language the engineer speaks (English, Finnish, German, French, Italian, Swedish...), but always send the tool an English question.
If they want to SEE something ("show me the kitchen", "take me to the bedrooms", "where is the bathroom"), call fly_to and then briefly
describe what they're looking at (how many, sizes if known). Counting questions still go to ask_plansight.
If they ask what PlanSight is: it answers questions about construction drawings with exact geometry, fine-tuned detectors and NVIDIA
Nemotron, shows the evidence on the sheet, and costs a fraction of a cent per question. Keep every reply under 3 sentences."""

TOOLS = [
    {
        "type": "client",
        "name": "ask_plansight",
        "description": "Ask PlanSight a question about the drawing currently open on screen. Returns the answer with evidence count and cost. "
                       "The UI highlights the evidence on the drawing while you speak.",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "One clear English question about the current drawing."}},
            "required": ["question"],
        },
        "expects_response": True,
        "response_timeout_secs": 20,
    },
    {
        "type": "client",
        "name": "open_drawing",
        "description": "Open a different drawing from the library by a word in its title or type (e.g. 'swiss', 'ifc', 'cubicasa', 'colorful 10062').",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Words to match against the drawing title or source type."}},
            "required": ["query"],
        },
        "expects_response": True,
        "response_timeout_secs": 10,
    },
    {
        "type": "client",
        "name": "fly_to",
        "description": "Lift the current floor plan into 3D and fly the camera through the rooms of one type, highlighting them "
                       "(e.g. 'kitchen', 'bedrooms', 'bathrooms', 'living room', 'balcony', 'corridor'). Use when the engineer says "
                       "'show me', 'take me to', 'where is', or asks to see rooms in 3D.",
        "parameters": {
            "type": "object",
            "properties": {"room": {"type": "string", "description": "Room type or name in English, e.g. 'kitchen' or 'bedrooms'."}},
            "required": ["room"],
        },
        "expects_response": True,
        "response_timeout_secs": 10,
    },
]


def upsert_tools() -> list[str]:
    existing = httpx.get(f"{API}/tools", headers=H, timeout=30).json().get("tools", [])
    by_name = {t["tool_config"]["name"]: t["id"] for t in existing if t.get("tool_config", {}).get("name")}
    ids = []
    for tool in TOOLS:
        if tool["name"] in by_name:
            r = httpx.patch(f"{API}/tools/{by_name[tool['name']]}", headers=H, json={"tool_config": tool}, timeout=30)
            r.raise_for_status(); ids.append(by_name[tool["name"]])
        else:
            r = httpx.post(f"{API}/tools", headers=H, json={"tool_config": tool}, timeout=30)
            if r.status_code >= 400:
                sys.exit(f"tool create failed {r.status_code}: {r.text[:800]}")
            ids.append(r.json()["id"])
    return ids


def main() -> None:
    tool_ids = upsert_tools()
    body = {
        "name": "PlanSight",
        "conversation_config": {
            "agent": {
                "first_message": "Hi, I'm PlanSight. Ask me anything about this drawing.",
                "language": "en",
                "prompt": {"prompt": PROMPT, "llm": "gemini-2.5-flash", "temperature": 0.2, "tool_ids": tool_ids,
                           "built_in_tools": {"language_detection": {"name": "language_detection", "params": {"system_tool_type": "language_detection"}}}},
            },
            "tts": {"model_id": "eleven_flash_v2"},
            "language_presets": {
                lang: {"overrides": {"agent": {"first_message": msg}, "tts": {"model_id": "eleven_flash_v2_5"}}}
                for lang, msg in {"fi": "Hei, olen PlanSight. Kysy mitä tahansa tästä piirustuksesta.",
                                  "de": "Hallo, ich bin PlanSight. Fragen Sie mich alles zu dieser Zeichnung.",
                                  "fr": "Bonjour, je suis PlanSight. Posez-moi vos questions sur ce plan.",
                                  "sv": "Hej, jag är PlanSight. Fråga mig vad som helst om den här ritningen."}.items()
            },
        },
    }
    agent_id = os.getenv("ELEVENLABS_AGENT_ID")
    if agent_id:
        r = httpx.patch(f"{API}/agents/{agent_id}", headers=H, json=body, timeout=30)
    else:
        r = httpx.post(f"{API}/agents/create", headers=H, json=body, timeout=30)
    if r.status_code >= 400:
        sys.exit(f"agent upsert failed {r.status_code}: {json.dumps(r.json())[:1500]}")
    agent_id = agent_id or r.json()["agent_id"]
    env = (ROOT / ".env").read_text(encoding="utf-8")
    if not re.search(r"^ELEVENLABS_AGENT_ID=\S", env, re.M):
        env = re.sub(r"^ELEVENLABS_AGENT_ID=.*\n?", "", env, flags=re.M).rstrip("\n") + f"\nELEVENLABS_AGENT_ID={agent_id}\n"
        (ROOT / ".env").write_text(env, encoding="utf-8")
    print("agent", agent_id, "tools", tool_ids)


if __name__ == "__main__":
    main()
