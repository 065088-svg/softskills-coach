"""SoftSkills Coach - MCQ role-play practice chatbot (use case 15).

Run:  streamlit run app.py
"""
from __future__ import annotations

import os
import random

import pandas as pd
import streamlit as st

from config import (
    APP_NAME,
    MAX_POINTS_PER_TURN,
    RATING_ICONS,
    RATING_LABELS,
    RATING_MEANING,
    SKILLS,
    TURNS_PER_SESSION,
)
from engine import (
    build_turn,
    fallback_debrief,
    fallback_turn,
    history_record,
    new_session,
    record_answer,
    skill_percent,
    summarise,
    validate_username,
    user_key,
)
from gemini_client import GeminiCoach, GeminiError, friendly_error, load_api_key
from scenarios import SCENARIOS, get_scenario
from storage import ProgressStore

st.set_page_config(page_title=APP_NAME, page_icon="💬", layout="centered")

LETTERS = "ABCD"


# ------------------------------------------------------------------ helpers
def md_safe(text):
    """Stop '$' from being read as LaTeX by Streamlit's markdown renderer."""
    return str(text).replace("$", "\\$")


def chip(rating):
    return f"{RATING_ICONS[rating]} {RATING_LABELS[rating]}"


@st.cache_resource(show_spinner=False)
def get_store():
    return ProgressStore()


@st.cache_resource(show_spinner=False)
def _make_coach(api_key, base_url):
    return GeminiCoach(api_key, base_url=base_url or None)


def resolve_api_key():
    """Priority: sidebar box > Streamlit secrets > .env / environment."""
    manual = (st.session_state.get("manual_key") or "").strip()
    if manual:
        return manual, "sidebar"
    try:
        secret = str(st.secrets.get("GEMINI_API_KEY", "")).strip()
    except Exception:  # no secrets file present
        secret = ""
    if secret:
        return secret, "Streamlit secrets"
    env = load_api_key()
    if env:
        return env, ".env file"
    return "", ""


def get_coach():
    """Return (coach, error_message). Never raises."""
    key, _ = resolve_api_key()
    if not key:
        return None, friendly_error(GeminiError("no_key", ""))
    try:
        return _make_coach(key, os.environ.get("GEMINI_BASE_URL", "")), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"Could not start the Gemini client: {type(exc).__name__}"


def persist(fn, *args):
    """Run a storage call; a read-only disk must not crash the app."""
    try:
        return fn(*args)
    except OSError:
        st.session_state["save_warning"] = True
        return None


# --------------------------------------------------------------- session ops
def begin_session(scenario_id, mode):
    scenario = get_scenario(scenario_id)
    session = new_session(scenario_id, "curated")
    notice = ""
    if mode == "live":
        coach, err = get_coach()
        if coach is None:
            notice = f"Live AI mode is unavailable ({err}) Using verified questions instead."
        else:
            session = new_session(scenario_id, "live")
            try:
                with st.spinner("Gemini is writing your scenario..."):
                    raw = coach.generate_turn(scenario, [], 0, TURNS_PER_SESSION, scenario["turns"][0]["skill"])
                session["turns"].append(build_turn(raw, random.Random(f"{session['seed']}-0"), source="live"))
            except GeminiError as exc:
                session = new_session(scenario_id, "curated")
                notice = f"Live AI mode failed ({friendly_error(exc)}) Using verified questions instead."
    session["notice"] = notice
    st.session_state["session"] = session
    persist(get_store().save_active, st.session_state["user"]["key"], st.session_state["user"]["display"], session)


def ensure_next_turn(session):
    """Make sure the turn the learner should see now exists (live mode builds it on demand)."""
    n = len(session["answers"])
    if n >= TURNS_PER_SESSION or len(session["turns"]) > n:
        return
    scenario = get_scenario(session["scenario_id"])
    coach, err = get_coach() if session["mode"] == "live" else (None, "")
    turn = None
    if coach is not None:
        try:
            with st.spinner("Gemini is writing the next question..."):
                raw = coach.generate_turn(scenario, session["answers"], n, TURNS_PER_SESSION,
                                          scenario["turns"][n]["skill"])
            turn = build_turn(raw, random.Random(f"{session['seed']}-{n}"), source="live")
        except GeminiError as exc:
            session["notice"] = f"Gemini could not write this question ({friendly_error(exc)}) Using a verified question."
    elif session["mode"] == "live":
        session["notice"] = f"Gemini is unavailable ({err}) Using a verified question."
    session["turns"].append(turn or fallback_turn(session, n))


def finish_session(session):
    summary = summarise(session)
    note = ""
    coach, _ = get_coach()
    if coach is not None:
        try:
            with st.spinner("Writing your coach's note..."):
                note = coach.generate_debrief(get_scenario(session["scenario_id"]), summary, session["answers"])
        except GeminiError:
            note = ""
    session["coach_note"] = note
    session["status"] = "finished"
    user = st.session_state["user"]
    persist(get_store().add_history, user["key"], user["display"], history_record(session, summary))


# ------------------------------------------------------------------- sidebar
def render_sidebar():
    with st.sidebar:
        st.header(f"💬 {APP_NAME}")
        st.caption("Use case 15 - Language / soft-skills practice chatbot")
        user = st.session_state.get("user")
        if user:
            st.success(f"Signed in as **{md_safe(user['display'])}**")
            if st.button("Switch user"):
                for k in ("user", "session", "resume_offer"):
                    st.session_state.pop(k, None)
                st.rerun()

        st.subheader("Gemini connection")
        key, source = resolve_api_key()
        if key:
            st.write(f"✅ API key loaded from {source}.")
            coach, _ = get_coach()
            if coach is not None and coach.working_model:
                st.caption(f"Last model used: `{coach.working_model}`")
        else:
            st.write("⚠️ No API key found. Verified mode still works; Live AI mode and the AI coach note need a key.")
            st.text_input("Paste Gemini API key (this session only)", type="password", key="manual_key",
                          help="Better: put it in the .env file once. See README.")

        with st.expander("🔒 Privacy & AI disclosure", expanded=False):
            st.markdown(
                "- You are using an **AI-powered tool**. Characters such as *Ms. Rao* are simulated.\n"
                "- Your only typed input is your display name. Everything else is multiple choice.\n"
                "- **Verified mode:** nothing is sent to any third party until the final screen, "
                "when your *scores and chosen answers* are sent to Gemini to write the coach note "
                "(only if an API key is set).\n"
                "- **Live AI mode:** the scenario text and your chosen answers are sent to Google's Gemini API "
                "to write each question. Your name is never sent.\n"
                "- Progress is stored locally in `data/progress.json`."
            )

        with st.expander("How scoring works"):
            for r in (3, 2, 1, 0):
                st.write(f"{chip(r)} ({r} pt) - {RATING_MEANING[r]}")

        if user:
            with st.expander("Progress file (backup / move devices)"):
                store = get_store()
                st.download_button("Download my progress", data=store.export_user(user["key"], user["display"]),
                                   file_name="softskills-progress.json", mime="application/json",
                                   )
                up = st.file_uploader("Restore from a progress file", type=["json"], key="import_file")
                if up is not None and st.session_state.get("imported_name") != (up.name, up.size):
                    ok, msg = store.import_user(user["key"], user["display"], up.getvalue().decode("utf-8", "replace"))
                    st.session_state["imported_name"] = (up.name, up.size)
                    (st.success if ok else st.error)(msg)


# --------------------------------------------------------------------- login
def render_login():
    st.title("💬 SoftSkills Coach")
    st.write("Practise real workplace conversations - interviews, customer calls, feedback talks - "
             "by choosing the best reply. You get instant grammar and tone feedback, and your progress "
             "is tracked across sessions.")
    st.info("🤖 This is an AI-powered practice tool. The people in the scenarios are simulated characters.")
    with st.form("login"):
        name = st.text_input("Your display name", max_chars=20, placeholder="e.g. Asha")
        go = st.form_submit_button("Start", type="primary")
    if go:
        ok, result = validate_username(name)
        if not ok:
            st.error(result)
            return
        key = user_key(result)
        st.session_state["user"] = {"display": result, "key": key}
        active = persist(get_store().load_active, key)
        if active:
            st.session_state["resume_offer"] = active
        st.rerun()


# ---------------------------------------------------------------------- home
def render_home():
    user = st.session_state["user"]
    store = get_store()
    st.title(f"Welcome, {md_safe(user['display'])} 👋")
    st.caption("🤖 AI-powered practice tool - the people in the scenarios are simulated.")

    offer = st.session_state.get("resume_offer")
    if offer:
        sc = get_scenario(offer["scenario_id"])
        with st.container(border=True):
            st.write(f"**Unfinished session:** {sc['title']} - {len(offer['answers'])}/{TURNS_PER_SESSION} answered.")
            c1, c2 = st.columns(2)
            if c1.button("Resume", type="primary"):
                st.session_state["session"] = offer
                st.session_state.pop("resume_offer", None)
                st.rerun()
            if c2.button("Discard"):
                persist(store.clear_active, user["key"])
                st.session_state.pop("resume_offer", None)
                st.rerun()

    history = store.get_history(user["key"])
    st.subheader("Your progress")
    if not history:
        st.write("No finished sessions yet. Pick a scenario below to begin.")
    else:
        avg = round(sum(r["percent"] for r in history) / len(history))
        c1, c2, c3 = st.columns(3)
        c1.metric("Sessions", len(history))
        c2.metric("Average score", f"{avg}%")
        c3.metric("Best score", f"{max(r['percent'] for r in history)}%")
        if len(history) >= 2:
            st.caption("Score per session (%)")
            st.line_chart(pd.DataFrame({"Score %": [r["percent"] for r in history]},
                                       index=range(1, len(history) + 1)))
        totals = {s: {"earned": 0, "max": 0} for s in SKILLS}
        for r in history:
            for s, v in r["skills"].items():
                totals[s]["earned"] += v["earned"]
                totals[s]["max"] += v["max"]
        rows = [(s, skill_percent(v)) for s, v in totals.items() if v["max"]]
        if rows:
            st.caption("Accuracy by skill, all sessions (%)")
            st.bar_chart(pd.DataFrame(rows, columns=["Skill", "Accuracy %"]).set_index("Skill"))
        with st.expander("Session history"):
            st.dataframe(pd.DataFrame([{
                "When (UTC)": r["finished_at"].replace("T", " ")[:16], "Scenario": r["scenario_title"],
                "Mode": r["mode"], "Score": f"{r['score']}/{r['max_score']}", "%": r["percent"]}
                for r in reversed(history)]), hide_index=True)

    st.subheader("Start a practice session")
    ids = [s["id"] for s in SCENARIOS]
    chosen = st.selectbox("Scenario", ids, format_func=lambda i: f"{get_scenario(i)['title']}  ({get_scenario(i)['category']})")
    sc = get_scenario(chosen)
    with st.container(border=True):
        st.markdown(f"**Setting:** {md_safe(sc['setting'])}")
        st.markdown(f"**You are practising with:** {md_safe(sc['partner'])} - {md_safe(sc['partner_role'])} *(simulated)*")
        st.markdown(f"**Your goal:** {md_safe(sc['goal'])}")
        best = [r for r in history if r["scenario_id"] == chosen]
        if best:
            st.caption(f"Your best here: {max(r['percent'] for r in best)}% over {len(best)} attempt(s).")
    mode_label = st.radio(
        "Question source",
        ["Verified questions (hand-checked, works offline)", "Live AI questions (Gemini writes each turn)"],
        help="Verified: every answer's rating was written and checked by the author. Live: Gemini writes the turns; "
             "the app validates the format, but the ratings are AI judgement.",
    )
    mode = "live" if mode_label.startswith("Live") else "curated"
    if st.button(f"Start - {TURNS_PER_SESSION} questions", type="primary"):
        begin_session(chosen, mode)
        st.rerun()


# ------------------------------------------------------------------ practice
def show_transcript_pair(session, i, scenario):
    turn, ans = session["turns"][i], session["answers"][i]
    with st.chat_message("assistant", avatar="🧑‍💼"):
        st.markdown(f"**{md_safe(scenario['partner'])}** *(simulated)*")
        st.write(md_safe(turn["partner_line"]))
    with st.chat_message("user"):
        st.write(md_safe(ans["chosen_text"]))
        st.caption(f"{chip(ans['rating'])} - {turn['skill']}")
    st.caption(f"*{md_safe(scenario['reactions'][ans['rating']])}*")


def render_practice():
    session = st.session_state["session"]
    user = st.session_state["user"]
    store = get_store()
    scenario = get_scenario(session["scenario_id"])

    if not session["review"]:
        ensure_next_turn(session)
    n = len(session["answers"])
    shown = n if session["review"] else n + 1

    st.title(scenario["title"])
    st.progress(min(shown, TURNS_PER_SESSION) / TURNS_PER_SESSION, text=f"Question {min(shown, TURNS_PER_SESSION)} of {TURNS_PER_SESSION}")
    st.caption(f"🤖 AI-powered practice. {md_safe(scenario['partner'])} is a simulated character. "
               f"Source: {'Live AI (Gemini)' if session['mode'] == 'live' else 'Verified questions'}")
    if session.get("notice"):
        st.warning(session["notice"])
    with st.expander("Scene", expanded=(n == 0 and not session["review"])):
        st.markdown(f"**Setting:** {md_safe(scenario['setting'])}  \n**Your goal:** {md_safe(scenario['goal'])}")

    done_before = n - 1 if session["review"] else n
    for i in range(done_before):
        show_transcript_pair(session, i, scenario)

    if session["review"]:
        render_review(session, scenario, n - 1)
    else:
        render_question(session, scenario, n)

    persist(store.save_active, user["key"], user["display"], session)
    with st.sidebar:
        if st.button("End session without saving"):
            persist(store.clear_active, user["key"])
            st.session_state["session"] = None
            st.rerun()


def render_question(session, scenario, n):
    turn = session["turns"][n]
    with st.chat_message("assistant", avatar="🧑‍💼"):
        st.markdown(f"**{md_safe(scenario['partner'])}** *(simulated)*")
        st.write(md_safe(turn["partner_line"]))
    if turn.get("note"):
        st.info(f"📝 {md_safe(turn['note'])}")
    st.caption(f"Skill focus: **{turn['skill']}**")
    form_key = f"q_{session['id']}_{n}"
    with st.form(form_key):
        choice = st.radio(
            "Choose your reply",
            options=list(range(len(turn["options"]))),
            index=None,
            format_func=lambda i: f"{LETTERS[i]}.  {md_safe(turn['options'][i]['text'])}",
            key=f"choice_{session['id']}_{n}",
        )
        submitted = st.form_submit_button("Submit answer", type="primary")
    if submitted:
        if choice is None:
            st.warning("Please select one reply before submitting.")
        else:
            record_answer(session, choice)   # idempotent: a double submit is ignored
            user = st.session_state["user"]
            persist(get_store().save_active, user["key"], user["display"], session)
            st.rerun()


def render_review(session, scenario, i):
    turn, ans = session["turns"][i], session["answers"][i]
    with st.chat_message("assistant", avatar="🧑‍💼"):
        st.markdown(f"**{md_safe(scenario['partner'])}** *(simulated)*")
        st.write(md_safe(turn["partner_line"]))
    with st.chat_message("user"):
        st.write(md_safe(ans["chosen_text"]))
    st.caption(f"*{md_safe(scenario['reactions'][ans['rating']])}*")

    if ans["rating"] == MAX_POINTS_PER_TURN:
        st.success(f"{chip(ans['rating'])} - +{ans['rating']} points")
    else:
        st.warning(f"{chip(ans['rating'])} - +{ans['rating']} of {MAX_POINTS_PER_TURN} points")
    st.markdown(f"**Why:** {md_safe(turn['options'][ans['chosen_index']]['feedback'])}")
    with st.expander("See all four replies and feedback", expanded=ans["rating"] < MAX_POINTS_PER_TURN):
        for j, o in enumerate(turn["options"]):
            mark = "  **<- your choice**" if j == ans["chosen_index"] else ""
            st.markdown(f"**{LETTERS[j]}. {chip(o['rating'])}**{mark}  \n{md_safe(o['text'])}  \n*{md_safe(o['feedback'])}*")
    st.info(f"💡 {md_safe(turn['tip'])}")

    flag_key = f"flagged_{session['id']}_{i}"
    c1, c2 = st.columns([1, 1])
    last = len(session["answers"]) >= TURNS_PER_SESSION
    if c1.button("See results" if last else "Next question", type="primary",
                 key=f"next_{session['id']}_{i}"):
        session["review"] = False
        if last:
            finish_session(session)
        st.session_state["session"] = session
        st.rerun()
    if st.session_state.get(flag_key):
        c2.caption("🚩 Thanks - reported for review.")
    elif c2.button("🚩 Report this question", key=f"flagbtn_{session['id']}_{i}"):
        persist(get_store().add_flag, st.session_state["user"]["key"], session, i, "reported by learner")
        st.session_state[flag_key] = True
        st.rerun()


# ------------------------------------------------------------------- results
def render_results(session):
    scenario = get_scenario(session["scenario_id"])
    summary = summarise(session)
    st.title("Results")
    st.subheader(scenario["title"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Score", f"{summary['score']}/{summary['max_score']}")
    c2.metric("Percent", f"{summary['percent']}%")
    c3.metric("Level", summary["band"])

    st.markdown("#### By skill")
    for skill, stats in summary["skills"].items():
        pct = skill_percent(stats)
        st.progress(pct / 100, text=f"{skill}: {stats['earned']}/{stats['max']} ({pct}%)")

    st.markdown("#### Coach's note")
    st.write(md_safe(fallback_debrief(summary)))
    if session.get("coach_note"):
        with st.container(border=True):
            st.markdown("**🤖 AI coach note** (written by Gemini from your results - may contain mistakes)")
            st.write(md_safe(session["coach_note"]))
    else:
        st.caption("AI coach note not available (no API key or Gemini could not be reached). Your score and progress are saved.")

    to_review = [a for a in session["answers"] if a["rating"] < MAX_POINTS_PER_TURN]
    st.markdown("#### Review")
    if not to_review:
        st.success("You chose the best reply every time. Try a different scenario for a new challenge.")
    for a in to_review:
        with st.expander(f"Question {a['turn_index'] + 1} - {a['skill']} - {chip(a['rating'])}"):
            st.markdown(f"**They said:** {md_safe(a['partner_line'])}")
            st.markdown(f"**You chose:** {md_safe(a['chosen_text'])}")
            st.markdown(f"**Best reply:** {md_safe(a['best_text'])}")

    b1, b2 = st.columns(2)
    if b1.button("Practise this scenario again", type="primary"):
        begin_session(session["scenario_id"], "live" if session["mode"] == "live" else "curated")
        st.rerun()
    if b2.button("Back to home"):
        st.session_state["session"] = None
        st.rerun()


# ---------------------------------------------------------------------- main
def main():
    render_sidebar()
    if not st.session_state.get("user"):
        render_login()
        return
    if st.session_state.pop("save_warning", False):
        st.warning("Progress could not be saved to disk on this server (read-only or full). "
                   "Use 'Download my progress' in the sidebar to keep a copy.")
    session = st.session_state.get("session")
    if session is None:
        render_home()
    elif session["status"] == "finished":
        render_results(session)
    else:
        render_practice()


main()
