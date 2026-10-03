"""End-to-end UI tests using Streamlit's AppTest (simulated browser)."""
import json
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import gemini_client
from config import PROGRESS_FILE
from fake_gemini import FakeGemini

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    st.cache_resource.clear()
    gemini_client._DEAD.clear()
    for n in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_BASE_URL", "GEMINI_MODEL"):
        monkeypatch.delenv(n, raising=False)
    # make sure a developer's real .env cannot leak into tests
    monkeypatch.setattr(gemini_client, "load_dotenv", lambda *a, **k: None)
    yield
    st.cache_resource.clear()


@pytest.fixture
def fake():
    f = FakeGemini().start()
    yield f
    f.stop()


def new_app():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def click(at, label):
    for b in list(at.button):
        if b.label == label:
            b.click().run()
            assert not at.exception, at.exception
            return
    raise AssertionError(f"button {label!r} not found; have {[b.label for b in at.button]}")


def has_button(at, label):
    return any(b.label == label for b in at.button)


def login(at, name):
    next(t for t in at.text_input if t.label == "Your display name").set_value(name)
    click(at, "Start")


def pick(at, rating):
    """Choose the option with the given rating in the current question and submit."""
    s = at.session_state["session"]
    turn = s["turns"][len(s["answers"])]
    idx = next(i for i, o in enumerate(turn["options"]) if o["rating"] == rating)
    at.radio[0].set_value(idx)
    click(at, "Submit answer")
    return idx


def start_scenario(at, mode="curated", scenario_index=0):
    at.selectbox[0].select_index(scenario_index).run()
    if mode == "live":
        at.radio[0].set_value(at.radio[0].options[1]).run()
    click(at, "Start - 5 questions")


def play_all(at, ratings):
    for i, r in enumerate(ratings):
        pick(at, r)
        click(at, "See results" if i == len(ratings) - 1 else "Next question")


# ---------------------------------------------------------------------- tests
def test_login_validation():
    at = new_app()
    login(at, "<script>")
    assert at.error and "2-20" in at.error[0].value
    assert at.session_state["user"] is None if "user" in at.session_state else True


def test_full_curated_session_scores_and_saves(tmp_path):
    at = new_app()
    login(at, "Perfect Pat")
    assert any("Welcome" in t.value for t in at.title)
    start_scenario(at)
    play_all(at, [3, 3, 3, 3, 3])
    metrics = {m.label: m.value for m in at.metric}
    assert metrics == {"Score": "15/15", "Percent": "100%", "Level": "Strong"}
    assert any("best reply every time" in s.value for s in at.success)
    hist = json.loads(Path(PROGRESS_FILE).read_text(encoding="utf-8"))["users"]["perfect pat"]["history"]
    assert len(hist) == 1 and hist[0]["score"] == 15 and hist[0]["mode"] == "curated"
    # back to home shows progress
    click(at, "Back to home")
    assert {m.label: m.value for m in at.metric}["Sessions"] == "1"


def test_mixed_answers_score_and_review_section():
    at = new_app()
    login(at, "Mixed Max")
    start_scenario(at, scenario_index=2)
    play_all(at, [3, 2, 1, 0, 3])
    m = {x.label: x.value for x in at.metric}
    assert m["Score"] == "9/15" and m["Percent"] == "60%" and m["Level"] == "Developing"
    # three questions were not best -> three review expanders
    assert len([e for e in at.expander if e.label.startswith("Question ")]) == 3


def test_submit_without_choice_warns_and_does_not_advance():
    at = new_app()
    login(at, "Empty Eve")
    start_scenario(at)
    click(at, "Submit answer")
    assert at.warning and "select one reply" in at.warning[0].value
    assert len(at.session_state["session"]["answers"]) == 0


def test_feedback_shows_correct_best_and_points():
    at = new_app()
    login(at, "Feedback Fay")
    start_scenario(at)
    pick(at, 1)
    assert any("Weak" in w.value and "+1 of 3" in w.value for w in at.warning)
    assert any("Why:" in m.value for m in at.markdown)
    # the "all replies" expander lists exactly four options with distinct ratings
    ex = next(e for e in at.expander if e.label.startswith("See all four"))
    text = " ".join(m.value for m in ex.markdown)
    for label in ("Best", "Acceptable", "Weak", "Poor"):
        assert text.count(label) == 1


def test_refresh_resumes_unfinished_session():
    at = new_app()
    login(at, "Resume Rae")
    start_scenario(at)
    pick(at, 3); click(at, "Next question")
    pick(at, 2); click(at, "Next question")
    answered = list(at.session_state["session"]["answers"])
    # --- simulate a browser refresh: brand-new session state, same user
    at2 = new_app()
    login(at2, "resume rae")                   # name is case-insensitive
    assert has_button(at2, "Resume")
    click(at2, "Resume")
    s = at2.session_state["session"]
    assert s["answers"] == answered and len(s["answers"]) == 2
    pick(at2, 3)                                # continues at question 3
    assert len(at2.session_state["session"]["answers"]) == 3


def test_discard_resume_offer():
    at = new_app()
    login(at, "Discard Dan")
    start_scenario(at)
    pick(at, 3)
    at2 = new_app()
    login(at2, "Discard Dan")
    click(at2, "Discard")
    assert not has_button(at2, "Resume")
    at3 = new_app()
    login(at3, "Discard Dan")
    assert not has_button(at3, "Resume")


def test_progress_accumulates_across_sessions():
    at = new_app()
    login(at, "Multi Mia")
    for ratings in ([3, 3, 3, 3, 3], [0, 0, 0, 0, 0], [3, 2, 3, 2, 3]):
        start_scenario(at)
        play_all(at, ratings)
        click(at, "Back to home")
    m = {x.label: x.value for x in at.metric}
    assert m["Sessions"] == "3" and m["Best score"] == "100%"
    assert m["Average score"] == f"{round((100 + 0 + round(100 * 13 / 15)) / 3)}%"
    kinds = {e.type for e in at.main}
    assert "arrow_line_chart" in kinds or "vega_lite_chart" in kinds or len(at.get("vega_lite_chart")) >= 1, kinds


def test_two_users_do_not_share_history():
    a = new_app(); login(a, "User One"); start_scenario(a); play_all(a, [3] * 5)
    b = new_app(); login(b, "User Two")
    assert "No finished sessions yet" in " ".join(m.value for m in b.markdown)


def test_report_question_writes_flag():
    at = new_app()
    login(at, "Flag Fred")
    start_scenario(at)
    pick(at, 3)
    click(at, "🚩 Report this question")
    flags = json.loads(Path(PROGRESS_FILE).read_text(encoding="utf-8"))["flags"]
    assert any(f["user"] == "flag fred" for f in flags)
    assert not has_button(at, "🚩 Report this question")        # cannot be spammed


def test_without_key_live_mode_falls_back_with_notice():
    at = new_app()
    login(at, "Nokey Nia")
    start_scenario(at, mode="live")
    s = at.session_state["session"]
    assert s["mode"] == "curated" and all(t["source"] == "curated" for t in s["turns"])
    assert at.warning and "Live AI mode is unavailable" in at.warning[0].value


def test_live_mode_end_to_end_with_fake_gemini(monkeypatch, fake):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_BASE_URL", fake.url)
    st.cache_resource.clear()
    at = new_app()
    login(at, "Livia Lane")
    start_scenario(at, mode="live")
    s = at.session_state["session"]
    assert s["mode"] == "live" and s["turns"][0]["source"] == "live"
    play_all(at, [3, 3, 2, 3, 1])
    assert all(t["source"] == "live" for t in at.session_state["session"]["turns"])
    assert {x.label: x.value for x in at.metric}["Score"] == "12/15"
    # AI coach note shown, labelled as AI-generated
    assert any("AI coach note" in m.value for m in at.markdown)
    # privacy: the user's name never reaches the API
    assert all("Livia" not in json.dumps(r["body"]) for r in fake.posts())
    # 5 live turns + 1 debrief
    assert len(fake.posts()) == 6
    hist = json.loads(Path(PROGRESS_FILE).read_text(encoding="utf-8"))["users"]["livia lane"]["history"]
    assert hist[0]["mode"] == "live" and hist[0]["coach_note"]


def test_live_start_failure_falls_back_to_verified(monkeypatch, fake):
    fake.global_status = 429
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_BASE_URL", fake.url)
    st.cache_resource.clear()
    at = new_app()
    login(at, "Quota Quin")
    start_scenario(at, mode="live")
    s = at.session_state["session"]
    assert s["mode"] == "curated" and len(s["turns"]) == 5
    assert "limit" in at.warning[0].value.lower()
    play_all(at, [3] * 5)                           # still fully playable
    assert {x.label: x.value for x in at.metric}["Score"] == "15/15"
    assert any("not available" in c.value for c in at.caption)      # no AI note, no crash


def test_live_mid_session_failure_switches_to_verified_turn(monkeypatch, fake):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_BASE_URL", fake.url)
    st.cache_resource.clear()
    at = new_app()
    login(at, "Mid Mona")
    start_scenario(at, mode="live")
    pick(at, 3)
    fake.global_status = 500                          # API goes down after question 1
    click(at, "Next question")
    s = at.session_state["session"]
    assert s["turns"][0]["source"] == "live" and s["turns"][1]["source"] == "curated"
    assert "verified question" in s["notice"]
    pick(at, 3); click(at, "Next question")
    pick(at, 3); click(at, "Next question")
    pick(at, 3); click(at, "Next question")
    pick(at, 3); click(at, "See results")
    assert {x.label: x.value for x in at.metric}["Score"] == "15/15"


def test_live_garbage_output_never_reaches_user(monkeypatch, fake):
    fake.turn_modes = ["bad_ratings", "bad_ratings"]
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_BASE_URL", fake.url)
    st.cache_resource.clear()
    at = new_app()
    login(at, "Garbage Gus")
    start_scenario(at, mode="live")
    s = at.session_state["session"]
    assert s["mode"] == "curated"                      # rejected, fell back
    for t in s["turns"]:
        assert sorted(o["rating"] for o in t["options"]) == [0, 1, 2, 3]


def test_sidebar_key_box_visible_without_key():
    at = new_app()
    assert any("No API key found" in m.value for m in at.sidebar.markdown) or \
           any("No API key found" in str(m.value) for m in at.sidebar.markdown)
