import json

import pytest

import engine
from storage import ProgressStore


@pytest.fixture
def store(tmp_path):
    return ProgressStore(tmp_path / "p.json")


def rec(sid="abc", pct_pts=12):
    s = engine.new_session("job_interview", "curated", seed=1)
    summary = {"score": pct_pts, "max_score": 15, "percent": round(100 * pct_pts / 15),
               "skills": {"Tone": {"earned": pct_pts, "max": 15}}}
    r = engine.history_record(s, dict(summary, band="x"))
    r["session_id"] = sid
    return r


def test_history_roundtrip_and_dedupe(store):
    assert store.add_history("asha", "Asha", rec("s1")) is True
    assert store.add_history("asha", "Asha", rec("s1")) is False       # same session id
    assert store.add_history("asha", "Asha", rec("s2", 9)) is True
    assert [r["session_id"] for r in store.get_history("asha")] == ["s1", "s2"]
    assert store.get_history("someone-else") == []


def test_active_session_resume_and_clear(store):
    s = engine.new_session("job_interview", "curated", seed=4)
    engine.record_answer(s, 1)
    store.save_active("asha", "Asha", s)
    assert store.load_active("asha")["answers"] == s["answers"]
    store.clear_active("asha")
    assert store.load_active("asha") is None


def test_tampered_active_session_is_dropped(store):
    s = engine.new_session("job_interview", "curated", seed=4)
    s["scenario_id"] = "ghost"
    store.save_active("asha", "Asha", s)
    assert store.load_active("asha") is None


def test_finishing_clears_active(store):
    s = engine.new_session("job_interview", "curated", seed=4)
    store.save_active("asha", "Asha", s)
    store.add_history("asha", "Asha", rec("s9"))
    assert store.load_active("asha") is None


def test_corrupt_file_is_quarantined_not_fatal(tmp_path):
    p = tmp_path / "p.json"
    p.write_text("{ this is not json", encoding="utf-8")
    store = ProgressStore(p)
    assert store.get_history("asha") == []
    store.add_history("asha", "Asha", rec("s1"))
    assert len(store.get_history("asha")) == 1
    assert list(tmp_path.glob("p.corrupt-*.json"))


def test_wrong_structure_is_quarantined(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert ProgressStore(p).get_history("x") == []


def test_users_are_isolated(store):
    store.add_history("a", "A", rec("s1"))
    store.add_history("b", "B", rec("s2"))
    assert [r["session_id"] for r in store.get_history("a")] == ["s1"]
    assert [r["session_id"] for r in store.get_history("b")] == ["s2"]


def test_export_import_roundtrip(store, tmp_path):
    store.add_history("asha", "Asha", rec("s1"))
    store.add_history("asha", "Asha", rec("s2", 9))
    blob = store.export_user("asha", "Asha")
    other = ProgressStore(tmp_path / "other.json")
    ok, msg = other.import_user("asha", "Asha", blob)
    assert ok and "2" in msg
    ok, msg = other.import_user("asha", "Asha", blob)      # importing twice adds nothing
    assert ok and "0" in msg
    assert len(other.get_history("asha")) == 2


@pytest.mark.parametrize("blob", ["not json", "[]", json.dumps({"app": "other", "history": []}),
                                  json.dumps({"app": "softskills-coach", "history": "x"}), "x" * 2_000_000])
def test_bad_import_rejected(store, blob):
    ok, _ = store.import_user("asha", "Asha", blob)
    assert not ok and store.get_history("asha") == []


def test_import_skips_invalid_records(store):
    good, bad = rec("g1"), rec("b1")
    bad["score"] = 999
    blob = json.dumps({"app": "softskills-coach", "history": [good, bad, "junk"]})
    ok, msg = store.import_user("asha", "Asha", blob)
    assert ok and "Imported 1" in msg and "Skipped 2" in msg
    assert [r["session_id"] for r in store.get_history("asha")] == ["g1"]


def test_flag_is_saved_for_human_review(store):
    s = engine.new_session("job_interview", "curated", seed=4)
    store.add_flag("asha", s, 0, "x" * 1000)
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert len(data["flags"]) == 1 and len(data["flags"][0]["reason"]) == 300
    assert data["flags"][0]["partner_line"] == s["turns"][0]["partner_line"]
