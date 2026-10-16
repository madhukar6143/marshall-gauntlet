"""List Gemini models the current GEMINI_API_KEY can use for generateContent.

    python bench/list_gemini_models.py

Reads the key from GEMINI_API_KEY (or GOOGLE_API_KEY) in the environment.
"""
import os

from google import genai

key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
if not key:
    raise SystemExit("GEMINI_API_KEY not set in this environment.")

client = genai.Client(api_key=key)
print("models supporting generateContent:")
for m in client.models.list():
    actions = getattr(m, "supported_actions", None) or []
    if "generateContent" in actions:
        name = m.name.replace("models/", "")
        tag = "  <-- PRO" if "pro" in name.lower() else ""
        print(f"  {name}{tag}")
