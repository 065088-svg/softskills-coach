import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Must be set before config.py is imported anywhere.
_TMP = tempfile.mkdtemp(prefix="softskills-test-")
os.environ["SOFTSKILLS_PROGRESS_FILE"] = str(Path(_TMP) / "progress.json")
for _n in ("NO_PROXY", "no_proxy"):
    os.environ[_n] = ",".join(filter(None, [os.environ.get(_n, ""), "127.0.0.1", "localhost"]))
for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_MODEL", "GEMINI_BASE_URL"):
    os.environ.pop(name, None)
