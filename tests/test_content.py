"""Audit of the verified scenario bank: structure, rubric and gaming-resistance."""
import random

import pytest

from config import OPTIONS_PER_TURN, SKILLS, TURNS_PER_SESSION
from engine import build_turn, validate_raw_turn
from scenarios import SCENARIOS, get_scenario


def all_turns():
    for s in SCENARIOS:
        for i, t in enumerate(s["turns"]):
            yield s, i, t


def test_scenario_ids_unique_and_complete():
    ids = [s["id"] for s in SCENARIOS]
    assert len(ids) == len(set(ids)) >= 5
    for s in SCENARIOS:
        for key in ("title", "category", "partner", "partner_role", "setting", "goal", "reactions", "turns"):
            assert s[key], (s["id"], key)
        assert len(s["turns"]) == TURNS_PER_SESSION, s["id"]
        assert set(s["reactions"]) == {0, 1, 2, 3}, s["id"]


@pytest.mark.parametrize("scenario,idx,t", list(all_turns()), ids=lambda v: v if isinstance(v, (str, int)) else "")
def test_every_turn_is_valid(scenario, idx, t):
    ok, err = validate_raw_turn(t)
    assert ok, f"{scenario['id']} turn {idx + 1}: {err}"
    assert t["skill"] in SKILLS
    assert len(t["options"]) == OPTIONS_PER_TURN
    assert sorted(o["rating"] for o in t["options"]) == [0, 1, 2, 3]
    assert t["tip"].strip().endswith(".")


def test_no_duplicate_texts_across_bank():
    texts = [o["text"] for _, _, t in all_turns() for o in t["options"]]
    assert len(texts) == len(set(texts))


def test_length_is_not_a_clue_to_the_best_answer():
    """Guards against a 'pick the longest (or 2nd longest) reply' strategy."""
    from collections import Counter
    ranks = Counter()
    for _, _, t in all_turns():
        by_len = sorted(t["options"], key=lambda o: -len(o["text"]))
        ranks[next(i for i, o in enumerate(by_len, 1) if o["rating"] == 3)] += 1
    total = sum(ranks.values())
    print("length rank of the best reply:", sorted(ranks.items()))
    assert max(ranks.values()) / total <= 0.40           # no single rank dominates
    assert all(ranks[r] >= 3 for r in (1, 2, 3, 4))       # every rank occurs


def test_shuffle_spreads_best_answer_over_positions():
    positions = set()
    for seed in range(40):
        rng = random.Random(seed)
        for t in get_scenario("job_interview")["turns"]:
            positions.add(build_turn(t, rng)["best_index"])
    assert positions == {0, 1, 2, 3}


def test_shuffle_keeps_rating_attached_to_text():
    t = get_scenario("job_interview")["turns"][0]
    built = build_turn(t, random.Random(1))
    original = {o["text"]: (o["rating"], o["feedback"]) for o in t["options"]}
    for o in built["options"]:
        assert original[o["text"]] == (o["rating"], o["feedback"])
    assert built["options"][built["best_index"]]["rating"] == 3
