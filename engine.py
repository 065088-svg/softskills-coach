"""Pure-Python practice engine: no Streamlit, no network. Fully unit-tested."""
from __future__ import annotations

import copy
import datetime as dt
import random
import re
import uuid

from config import (
    MAX_POINTS_PER_TURN,
    OPTIONS_PER_TURN,
    SKILLS,
    TURNS_PER_SESSION,
    USERNAME_RE,
)
from scenarios import get_scenario

MODES = ("curated", "live")

# ----------------------------------------------------------------- text safety
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_WS_RE = re.compile(r"[ \t]+")


def clean_text(value, max_len=600):
    """Normalise untrusted text (e.g. model output): str only, no control chars."""
    if not isinstance(value, str):
        return ""
    value = _CTRL_RE.sub("", value).replace("\r", "")
    value = _WS_RE.sub(" ", value).strip()
    return value[:max_len]


# ------------------------------------------------------------------- usernames
def validate_username(raw):
    """Return (ok, cleaned_name_or_error_message)."""
    if not isinstance(raw, str):
        return False, "Please enter a name."
    name = " ".join(raw.split())
    if not USERNAME_RE.match(name):
        return False, ("Use 2-20 characters: letters, numbers, spaces, dot, dash or underscore "
                       "(must start with a letter or number).")
    return True, name


def user_key(name):
    return " ".join(name.lower().split())


# ----------------------------------------------------------------------- turns
def build_turn(raw_turn, rng, source="curated"):
    """Shuffle the four options and remember where the best one landed."""
    options = copy.deepcopy(raw_turn["options"])
    rng.shuffle(options)
    best_index = next(i for i, o in enumerate(options) if o["rating"] == 3)
    return {
        "skill": raw_turn["skill"],
        "partner_line": raw_turn["partner_line"],
        "note": raw_turn.get("note", ""),
        "tip": raw_turn.get("tip", ""),
        "options": options,
        "best_index": best_index,
        "source": source,
    }


def validate_raw_turn(raw):
    """Strict validation used for AI-generated turns. Returns (ok, error)."""
    if not isinstance(raw, dict):
        return False, "turn is not an object"
    for key in ("partner_line", "tip"):
        if not clean_text(raw.get(key)):
            return False, f"missing {key}"
    if len(clean_text(raw["partner_line"], 2000)) > 400:
        return False, "partner_line too long"
    options = raw.get("options")
    if not isinstance(options, list) or len(options) != OPTIONS_PER_TURN:
        return False, f"need exactly {OPTIONS_PER_TURN} options"
    ratings, texts = [], set()
    for o in options:
        if not isinstance(o, dict):
            return False, "option is not an object"
        r = o.get("rating")
        if isinstance(r, bool) or not isinstance(r, int) or r not in (0, 1, 2, 3):
            return False, "rating must be an integer 0-3"
        text, fb = clean_text(o.get("text"), 2000), clean_text(o.get("feedback"), 2000)
        if not text or not fb:
            return False, "option text/feedback empty"
        if len(text) > 400 or len(fb) > 400:
            return False, "option text/feedback too long"
        if text.lower() in texts:
            return False, "duplicate option text"
        texts.add(text.lower())
        ratings.append(r)
    if sorted(ratings) != [0, 1, 2, 3]:
        return False, "ratings must be exactly 0,1,2,3 once each"
    return True, ""


def normalise_live_turn(raw, skill):
    """Return a cleaned raw turn dict (same shape as the curated bank)."""
    ok, err = validate_raw_turn(raw)
    if not ok:
        raise ValueError(err)
    return {
        "skill": skill,
        "partner_line": clean_text(raw["partner_line"], 400),
        "note": clean_text(raw.get("note", ""), 300),
        "tip": clean_text(raw["tip"], 300),
        "options": [
            {
                "rating": o["rating"],
                "text": clean_text(o["text"], 400),
                "feedback": clean_text(o["feedback"], 400),
            }
            for o in raw["options"]
        ],
    }


# -------------------------------------------------------------------- sessions
def new_session(scenario_id, mode, seed=None):
    scenario = get_scenario(scenario_id)
    if scenario is None:
        raise ValueError(f"unknown scenario: {scenario_id}")
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")
    seed = int(seed) if seed is not None else random.SystemRandom().randrange(1, 2**31)
    session = {
        "id": uuid.uuid4().hex[:12],
        "scenario_id": scenario_id,
        "mode": mode,
        "seed": seed,
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "turns": [],
        "answers": [],
        "status": "active",
        "review": False,   # True right after answering, until the learner clicks Next
        "notice": "",
        "coach_note": "",
    }
    if mode == "curated":
        session["turns"] = curated_turns(scenario_id, seed)
    return session


def curated_turns(scenario_id, seed):
    scenario = get_scenario(scenario_id)
    rng = random.Random(seed)
    return [build_turn(t, rng) for t in scenario["turns"]]


def fallback_turn(session, turn_index):
    """Curated turn for this position (used when live generation fails)."""
    scenario = get_scenario(session["scenario_id"])
    rng = random.Random(f"{session['seed']}-{turn_index}")
    return build_turn(scenario["turns"][turn_index], rng, source="curated")


def current_index(session):
    return len(session["answers"])


def awaiting_answer(session):
    """True if the next turn exists, is unanswered, and we are not in the review step."""
    return len(session["turns"]) > len(session["answers"]) and not session.get("review")


def is_complete(session):
    return len(session["answers"]) >= TURNS_PER_SESSION


def record_answer(session, chosen_index):
    """Score the learner's choice. Idempotent: a second call for the same turn is ignored."""
    if session["status"] != "active" or not awaiting_answer(session):
        return None
    if isinstance(chosen_index, bool) or not isinstance(chosen_index, int) \
            or not 0 <= chosen_index < OPTIONS_PER_TURN:
        raise ValueError("chosen_index out of range")
    idx = len(session["answers"])
    turn = session["turns"][idx]
    chosen = turn["options"][chosen_index]
    best = turn["options"][turn["best_index"]]
    session["review"] = True
    answer = {
        "turn_index": idx,
        "skill": turn["skill"],
        "chosen_index": chosen_index,
        "rating": chosen["rating"],
        "chosen_text": chosen["text"],
        "best_text": best["text"],
        "partner_line": turn["partner_line"],
    }
    session["answers"].append(answer)
    return answer


# --------------------------------------------------------------------- results
def band_for(percent):
    if percent >= 80:
        return "Strong"
    if percent >= 60:
        return "Developing"
    return "Needs practice"


def summarise(session):
    answers = session["answers"]
    score = sum(a["rating"] for a in answers)
    max_score = MAX_POINTS_PER_TURN * len(answers)
    percent = round(100 * score / max_score) if max_score else 0
    skills = {}
    for a in answers:
        s = skills.setdefault(a["skill"], {"earned": 0, "max": 0})
        s["earned"] += a["rating"]
        s["max"] += MAX_POINTS_PER_TURN
    return {
        "score": score,
        "max_score": max_score,
        "percent": percent,
        "band": band_for(percent),
        "skills": skills,
        "best_count": sum(1 for a in answers if a["rating"] == 3),
        "turns": len(answers),
    }


def skill_percent(skill_stats):
    return round(100 * skill_stats["earned"] / skill_stats["max"]) if skill_stats["max"] else 0


def strongest_and_weakest(skills):
    if not skills:
        return None, None
    ranked = sorted(skills.items(), key=lambda kv: (-skill_percent(kv[1]), kv[0]))
    return ranked[0][0], ranked[-1][0]


def fallback_debrief(summary):
    """Deterministic coach note (used whenever the AI note is unavailable)."""
    strong, weak = strongest_and_weakest(summary["skills"])
    parts = [f"You chose the best reply in {summary['best_count']} of {summary['turns']} questions "
             f"({summary['score']}/{summary['max_score']} points, {summary['band']})."]
    if strong and weak and strong != weak:
        parts.append(f"Your strongest area was {strong}; focus next on {weak}.")
    elif strong:
        parts.append(f"This session tested {strong}.")
    parts.append("Review the questions marked below, then try the same scenario again or pick a new one.")
    return " ".join(parts)


def history_record(session, summary, finished_at=None):
    scenario = get_scenario(session["scenario_id"])
    return {
        "session_id": session["id"],
        "scenario_id": session["scenario_id"],
        "scenario_title": scenario["title"] if scenario else session["scenario_id"],
        "mode": session["mode"],
        "finished_at": finished_at or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "score": summary["score"],
        "max_score": summary["max_score"],
        "percent": summary["percent"],
        "skills": summary["skills"],
        "coach_note": session.get("coach_note", ""),
    }


def validate_history_record(rec):
    """Strict check for records loaded from a file the user imported."""
    if not isinstance(rec, dict):
        return False
    try:
        if not isinstance(rec.get("session_id"), str) or not rec["session_id"] or len(rec["session_id"]) > 64:
            return False
        if rec.get("mode") not in MODES:
            return False
        for k in ("score", "max_score", "percent"):
            if isinstance(rec.get(k), bool) or not isinstance(rec.get(k), int):
                return False
        if not (0 < rec["max_score"] <= 3 * 50 and 0 <= rec["score"] <= rec["max_score"]):
            return False
        if rec["percent"] != round(100 * rec["score"] / rec["max_score"]):
            return False
        if not isinstance(rec.get("scenario_title"), str) or not isinstance(rec.get("finished_at"), str):
            return False
        skills = rec.get("skills")
        if not isinstance(skills, dict):
            return False
        for name, st in skills.items():
            if name not in SKILLS or not isinstance(st, dict):
                return False
            e, m = st.get("earned"), st.get("max")
            if isinstance(e, bool) or isinstance(m, bool) or not isinstance(e, int) or not isinstance(m, int):
                return False
            if not (0 <= e <= m):
                return False
    except (KeyError, TypeError):
        return False
    return True


def validate_session(obj):
    """Check a session loaded from disk before resuming it."""
    try:
        if not isinstance(obj, dict) or obj.get("status") != "active":
            return False
        if obj.get("mode") not in MODES or get_scenario(obj.get("scenario_id")) is None:
            return False
        turns, answers = obj.get("turns"), obj.get("answers")
        if not isinstance(turns, list) or not isinstance(answers, list):
            return False
        if not (len(answers) <= len(turns) <= TURNS_PER_SESSION) or len(answers) >= TURNS_PER_SESSION + 1:
            return False
        for t in turns:
            ok, _ = validate_raw_turn(t)
            if not ok or t.get("skill") not in SKILLS:
                return False
            if not isinstance(t.get("best_index"), int) or t["options"][t["best_index"]]["rating"] != 3:
                return False
        for i, a in enumerate(answers):
            if a.get("turn_index") != i or turns[i]["options"][a["chosen_index"]]["rating"] != a.get("rating"):
                return False
        if obj["mode"] == "curated" and len(turns) != TURNS_PER_SESSION:
            return False
        return isinstance(obj.get("id"), str) and isinstance(obj.get("seed"), int)
    except (KeyError, TypeError, IndexError):
        return False
