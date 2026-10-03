import json

import pytest

import gemini_client
from gemini_client import GeminiCoach, GeminiError
from scenarios import get_scenario
from fake_gemini import FakeGemini


@pytest.fixture
def fake():
    gemini_client._DEAD.clear()
    f = FakeGemini().start()
    yield f
    f.stop()
    gemini_client._DEAD.clear()


def coach(fake, **kw):
    return GeminiCoach("test-key-123", base_url=fake.url, **kw)


SC = get_scenario("job_interview")


def test_generate_turn_happy_path_and_request_shape(fake):
    c = coach(fake)
    history = [{"turn_index": 0, "partner_line": "Hi", "chosen_text": "Hello", "rating": 3}]
    t = c.generate_turn(SC, history, 1, 5, "Grammar")
    assert t["skill"] == "Grammar" and len(t["options"]) == 4
    req = fake.posts()[0]
    cfg = req["body"]["generationConfig"]
    assert cfg["responseMimeType"] == "application/json"
    assert cfg["responseSchema"]["properties"]["options"]["type"] == "ARRAY"
    assert req["headers"].get("x-goog-api-key") == "test-key-123"
    user_text = req["body"]["contents"][0]["parts"][0]["text"]
    payload = json.loads(user_text.split("\n", 1)[1])
    assert payload["focus_skill"] == "Grammar" and payload["turn_number"] == 2
    assert payload["history"][0]["reply_quality"] == "Best"
    assert "ONE turn" in req["body"]["systemInstruction"]["parts"][0]["text"]
    assert c.working_model == "gemini-3.5-flash-lite"


def test_falls_back_to_next_model_on_404(fake):
    fake.ok_models = {"gemini-3.5-flash"}
    c = coach(fake)
    assert c.generate_turn(SC, [], 0, 5, "Clarity")["skill"] == "Clarity"
    assert [r["model"] for r in fake.posts()] == ["gemini-3.5-flash-lite", "gemini-3.5-flash"]
    assert c.working_model == "gemini-3.5-flash"
    # second call goes straight to the working model
    c.generate_turn(SC, [], 0, 5, "Clarity")
    assert fake.posts()[-1]["model"] == "gemini-3.5-flash"


def test_preferred_model_is_tried_first(fake):
    fake.ok_models = {"gemini-9.9-flash", "gemini-3.5-flash"}
    c = coach(fake, preferred_model="gemini-9.9-flash")
    c.generate_turn(SC, [], 0, 5, "Tone")
    assert fake.posts()[0]["model"] == "gemini-9.9-flash"


def test_discovers_models_when_defaults_are_unavailable(fake):
    fake.ok_models = {"gemini-3.7-flash"}
    fake.listed = ["gemini-3.7-flash", "gemini-3.7-flash-image", "gemini-2.0-flash-001", "text-embedding-004"]
    c = coach(fake)
    c.generate_turn(SC, [], 0, 5, "Tone")
    assert c.working_model == "gemini-3.7-flash"
    assert c.discover_models() == ["gemini-3.7-flash"]      # only stable flash ids


def test_quota_everywhere_raises_quota(fake):
    fake.global_status = 429
    with pytest.raises(GeminiError) as e:
        coach(fake).generate_turn(SC, [], 0, 5, "Tone")
    assert e.value.kind == "quota"


def test_models_that_hit_429_are_skipped_not_hammered(fake):
    fake.status_for = {"gemini-3.5-flash-lite": 429}
    c = coach(fake)
    c.generate_turn(SC, [], 0, 5, "Tone")
    assert c.working_model == "gemini-3.5-flash"
    n_before = len(fake.posts())
    fake.status_for = {}
    coach(fake).generate_turn(SC, [], 0, 5, "Tone")          # new coach, same process: lite is "dead" for now
    assert fake.posts()[n_before]["model"] == "gemini-3.5-flash"


def test_bad_key_is_auth_error_without_trying_other_models(fake):
    fake.global_status = 400            # fake returns "API key not valid"
    with pytest.raises(GeminiError) as e:
        coach(fake).generate_turn(SC, [], 0, 5, "Tone")
    assert e.value.kind == "auth" and len(fake.posts()) == 1


def test_server_error_retries_once_then_moves_on(fake):
    fake.status_for = {"gemini-3.5-flash-lite": 500}
    c = coach(fake)
    c.generate_turn(SC, [], 0, 5, "Tone")
    models = [r["model"] for r in fake.posts()]
    assert models[:2] == ["gemini-3.5-flash-lite"] * 2 and models[2] == "gemini-3.5-flash"


def test_garbage_then_good_is_retried(fake):
    fake.turn_modes = ["garbage"]
    t = coach(fake).generate_turn(SC, [], 0, 5, "Tone")
    assert len(t["options"]) == 4
    retry_prompt = fake.posts()[1]["body"]["contents"][0]["parts"][0]["text"]
    assert "previous output was invalid" in retry_prompt


@pytest.mark.parametrize("modes", [["garbage", "garbage"], ["bad_ratings", "bad_ratings"]])
def test_two_bad_outputs_raise_bad_output(fake, modes):
    fake.turn_modes = list(modes)
    with pytest.raises(GeminiError) as e:
        coach(fake).generate_turn(SC, [], 0, 5, "Tone")
    assert e.value.kind == "bad_output"


def test_empty_response_tries_next_model_then_fails_cleanly(fake):
    fake.turn_modes = ["empty"] * 10
    with pytest.raises(GeminiError) as e:
        coach(fake).generate_turn(SC, [], 0, 5, "Tone")
    assert e.value.kind == "bad_output"


def test_unreachable_server_is_network_error():
    c = GeminiCoach("k", base_url="http://127.0.0.1:9")      # nothing listens on port 9
    with pytest.raises(GeminiError) as e:
        c.generate_turn(SC, [], 0, 5, "Tone")
    assert e.value.kind == "network"


def test_debrief_is_cleaned_and_grounded(fake):
    fake.debrief_text = "**Great work!**\n# Tone was strong. Grammar needs care. Next, replay the scenario and watch articles."
    summary = {"score": 12, "max_score": 15, "band": "Strong", "skills": {"Tone": {"earned": 6, "max": 6}}}
    answers = [{"skill": "Tone", "rating": 3, "chosen_text": "A", "best_text": "A"},
               {"skill": "Grammar", "rating": 1, "chosen_text": "B", "best_text": "C"}]
    note = coach(fake).generate_debrief(SC, summary, answers)
    assert "*" not in note and "#" not in note and "\n" not in note
    sent = json.loads(fake.posts()[0]["body"]["contents"][0]["parts"][0]["text"].split("\n", 1)[1])
    assert sent["score"] == "12/15" and sent["answers"][1]["best_was"] == "C"
    assert sent["answers"][0]["best_was"] == "(same as chosen)"


def test_too_short_debrief_rejected(fake):
    fake.debrief_text = "Good."
    summary = {"score": 1, "max_score": 15, "band": "x", "skills": {}}
    with pytest.raises(GeminiError):
        coach(fake).generate_debrief(SC, summary, [])


def test_ping(fake):
    model, text = coach(fake).ping()
    assert model == "gemini-3.5-flash-lite" and text == "OK"


def test_no_key_raises():
    with pytest.raises(GeminiError) as e:
        GeminiCoach("")
    assert e.value.kind == "no_key"


def test_load_api_key_reads_env_and_strips_quotes(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ' "abc123" ')
    assert gemini_client.load_api_key() == "abc123"
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setenv("GOOGLE_API_KEY", "g-key")
    assert gemini_client.load_api_key() == "g-key"
