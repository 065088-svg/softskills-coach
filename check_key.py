"""Run this once to confirm your Gemini key works:   python check_key.py"""
import sys

from gemini_client import GeminiCoach, GeminiError, friendly_error, load_api_key


def main():
    key = load_api_key()
    if not key:
        print("X No key found. Copy .env.example to .env and paste your key after GEMINI_API_KEY=")
        return 1
    print(f"Key found (ends with ...{key[-4:]}). Testing the API...")
    try:
        coach = GeminiCoach(key)
        model, reply = coach.ping()
    except GeminiError as exc:
        print(f"X {friendly_error(exc)}\n  Detail: {exc.message}")
        return 1
    print(f"OK - Gemini answered using model '{model}': {reply}")
    print("Models your key can use (stable Flash):", ", ".join(coach.discover_models()) or "(none listed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
