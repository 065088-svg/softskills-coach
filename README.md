# SoftSkills Coach — MCQ role-play practice chatbot (Use case 15)

Language / soft-skills practice bot: conversational role-play scenarios, grammar and tone feedback, and progress tracking over multiple sessions. Every interaction is **multiple choice** (the only typed field is your display name).

## Run it in VS Code (5 steps)

1. Open this folder in VS Code (`File → Open Folder`). Open a terminal (`Ctrl+``).
2. Create the environment and install:
   ```
   python -m venv .venv
   .venv\Scripts\activate          # Windows   (Mac/Linux: source .venv/bin/activate)
   pip install -r requirements.txt
   ```
3. Get a free key at https://aistudio.google.com/apikey. Copy `.env.example` to a new file named `.env` and paste the key:
   ```
   GEMINI_API_KEY=your-key-here
   ```
4. Check the key (optional but recommended): `python check_key.py`  → should print `OK - Gemini answered using model ...`
5. Start the app: `streamlit run app.py` (opens http://localhost:8501)

No key? The app still works in **Verified** mode. You can also paste a key into the sidebar for one session.

## Two question sources
| Mode | What happens | Use it to show |
|---|---|---|
| Verified (default) | 6 scenarios × 5 hand-written questions. Ratings are fixed by the author, so scoring is deterministic and accurate. Works offline. | Accuracy, fallback behaviour |
| Live AI | Gemini writes each turn from the conversation so far (memory, reactions). Output is validated; invalid output falls back to Verified questions. | Prompt design, multi-turn memory, guardrails |

At the end of any session, Gemini (if a key is set) writes a short AI coach note from your real results.

## Get a shareable link (required deliverable)
1. Push this folder to a GitHub repo (`.env` is git-ignored, so your key is not uploaded).
2. Go to https://share.streamlit.io → New app → pick the repo → main file `app.py`.
3. In **Advanced settings → Secrets** paste: `GEMINI_API_KEY = "your-key-here"`.
4. Deploy, then submit the `*.streamlit.app` URL.
Note: free hosting has a temporary disk, so saved progress can reset when the app restarts. The sidebar has **Download / Restore progress** for that.

## Tests
`python -m pytest tests -q` → 147 tests (question-bank audit, scoring, storage, Gemini API paths against a local fake server, full UI flows).

## Files
`app.py` UI · `engine.py` scoring/validation · `scenarios.py` question bank · `gemini_client.py` API + model fallback · `storage.py` progress · `check_key.py` key test.

## Troubleshooting
- *“Gemini rejected the API key”* → re-copy the key, no quotes/spaces.
- *“None of the Gemini models tried is available”* → run `python check_key.py` to list models for your key, then set `GEMINI_MODEL=<id>` in `.env`.
- *“free-tier limit reached”* → wait a minute; the app falls back to Verified questions automatically.
