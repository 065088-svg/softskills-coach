"""Local JSON persistence for progress across sessions (and resume after refresh).

Names are only used as dictionary keys, never as file names, so there is no
path-traversal risk. Writes are atomic (temp file + replace).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
from pathlib import Path

from config import MAX_HISTORY_RECORDS, MAX_IMPORT_BYTES, PROGRESS_FILE
from engine import validate_history_record, validate_session

_LOCK = threading.RLock()
SCHEMA_VERSION = 1


def _empty():
    return {"version": SCHEMA_VERSION, "users": {}, "flags": []}


class ProgressStore:
    def __init__(self, path=PROGRESS_FILE):
        self.path = Path(path)

    # ---------------------------------------------------------------- file io
    def _read(self):
        if not self.path.exists():
            return _empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("users"), dict):
                raise ValueError("bad structure")
            data.setdefault("flags", [])
            data.setdefault("version", SCHEMA_VERSION)
            return data
        except (OSError, ValueError):
            # Keep the unreadable file for inspection and start fresh.
            try:
                stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                self.path.replace(self.path.with_name(f"{self.path.stem}.corrupt-{stamp}.json"))
            except OSError:
                pass
            return _empty()

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def _user(self, data, key, display=None):
        u = data["users"].setdefault(key, {"display": display or key, "history": [], "active": None})
        if display:
            u["display"] = display
        u.setdefault("history", [])
        u.setdefault("active", None)
        return u

    # ---------------------------------------------------------------- history
    def get_history(self, key):
        with _LOCK:
            return list(self._read()["users"].get(key, {}).get("history", []))

    def add_history(self, key, display, record):
        """Add a finished-session record. Duplicate session ids are ignored."""
        with _LOCK:
            data = self._read()
            u = self._user(data, key, display)
            if any(r.get("session_id") == record["session_id"] for r in u["history"]):
                return False
            u["history"].append(record)
            u["history"] = u["history"][-MAX_HISTORY_RECORDS:]
            u["active"] = None
            self._write(data)
            return True

    # ----------------------------------------------------------------- resume
    def save_active(self, key, display, session):
        with _LOCK:
            data = self._read()
            u = self._user(data, key, display)
            u["active"] = session
            self._write(data)

    def load_active(self, key):
        with _LOCK:
            u = self._read()["users"].get(key)
            if not u:
                return None
            active = u.get("active")
            if active is None:
                return None
            if validate_session(active):
                return active
            return None

    def clear_active(self, key):
        with _LOCK:
            data = self._read()
            if key in data["users"]:
                data["users"][key]["active"] = None
                self._write(data)

    # ------------------------------------------------------------ export/import
    def export_user(self, key, display):
        history = self.get_history(key)
        return json.dumps({"app": "softskills-coach", "version": SCHEMA_VERSION,
                           "display": display, "history": history}, ensure_ascii=False, indent=2)

    def import_user(self, key, display, text):
        """Merge history from an exported file. Returns (ok, message)."""
        if not isinstance(text, (str, bytes)):
            return False, "Could not read the file."
        if len(text) > MAX_IMPORT_BYTES:
            return False, "File is too large."
        try:
            payload = json.loads(text)
        except ValueError:
            return False, "This is not a valid progress file (invalid JSON)."
        if not isinstance(payload, dict) or payload.get("app") != "softskills-coach" \
                or not isinstance(payload.get("history"), list):
            return False, "This is not a SoftSkills Coach progress file."
        good = [r for r in payload["history"][:MAX_HISTORY_RECORDS] if validate_history_record(r)]
        skipped = len(payload["history"][:MAX_HISTORY_RECORDS]) - len(good)
        with _LOCK:
            data = self._read()
            u = self._user(data, key, display)
            known = {r.get("session_id") for r in u["history"]}
            added = [r for r in good if r["session_id"] not in known]
            u["history"] = sorted(u["history"] + added, key=lambda r: r.get("finished_at", ""))[-MAX_HISTORY_RECORDS:]
            self._write(data)
        msg = f"Imported {len(added)} session(s)."
        if skipped:
            msg += f" Skipped {skipped} invalid record(s)."
        return True, msg

    # ------------------------------------------------------------------ flags
    def add_flag(self, key, session, turn_index, reason):
        """Human review queue: the learner reports a question as wrong/unclear."""
        with _LOCK:
            data = self._read()
            turn = session["turns"][turn_index]
            data["flags"].append({
                "when": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "user": key,
                "scenario_id": session["scenario_id"],
                "mode": session["mode"],
                "turn_index": turn_index,
                "source": turn.get("source", ""),
                "partner_line": turn["partner_line"],
                "options": turn["options"],
                "reason": reason[:300],
            })
            data["flags"] = data["flags"][-500:]
            self._write(data)
