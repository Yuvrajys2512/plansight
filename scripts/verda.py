"""Tiny Verda instance control: python scripts/verda.py status|start|shutdown"""
import os, sys, httpx
from dotenv import load_dotenv

load_dotenv()
INSTANCE = "cfc2d9d2-7c64-4630-949e-a608a87c6333"
API = "https://api.verda.com/v1"


def token():
    r = httpx.post(f"{API}/oauth2/token", json={"grant_type": "client_credentials",
                   "client_id": os.environ["VERDA_CLIENT_ID"], "client_secret": os.environ["VERDA_CLIENT_SECRET"]}, timeout=30)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    h = token()
    if cmd == "status":
        i = httpx.get(f"{API}/instances/{INSTANCE}", headers=h, timeout=30).json()
        print(i.get("status"), i.get("ip"), i.get("hostname"))
        b = httpx.get(f"{API}/balance", headers=h, timeout=30).json()
        print("balance", b.get("amount"), b.get("currency"))
    elif cmd in ("start", "shutdown"):
        r = httpx.put(f"{API}/instances", headers=h, json={"id": INSTANCE, "action": cmd}, timeout=30)
        print(r.status_code, r.text[:300])


if __name__ == "__main__":
    main()
