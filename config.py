"""Central constants for SoftSkills Coach."""
from pathlib import Path
import os
import re

APP_NAME = "SoftSkills Coach"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PROGRESS_FILE = Path(os.environ.get("SOFTSKILLS_PROGRESS_FILE") or DATA_DIR / "progress.json")

SKILLS = ["Grammar", "Tone", "Clarity", "Empathy", "Assertiveness"]

# Rubric: every question has exactly four replies, one per rating.
RATING_POINTS = (3, 2, 1, 0)
RATING_LABELS = {
    3: "Best",
    2: "Acceptable",
    1: "Weak",
    0: "Poor",
}
RATING_ICONS = {3: "✅", 2: "🟡", 1: "🟠", 0: "🔴"}
RATING_MEANING = {
    3: "Correct, appropriate and effective.",
    2: "Correct and appropriate, but with one small gap (vague, blunt, or a minor slip).",
    1: "A noticeable problem that would hurt clarity or the impression you make.",
    0: "A serious error, or counter-productive in this situation.",
}

TURNS_PER_SESSION = 5
MAX_POINTS_PER_TURN = 3
OPTIONS_PER_TURN = 4

# Gemini model ids to try in order if GEMINI_MODEL is not set. The app also
# auto-discovers models for your key if none of these work (see gemini_client.py).
MODEL_CANDIDATES = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
]
GEMINI_TIMEOUT_MS = 30_000

# The only free-text field in the whole app is the display name.
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{1,19}$")

MAX_IMPORT_BYTES = 1_000_000
MAX_HISTORY_RECORDS = 500
