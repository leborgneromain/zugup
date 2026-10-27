from datetime import timedelta, timezone

from zugup.coach.advice import SPEED_LABELS, focus_axis, generate_advice
from zugup.i18n import translator
from zugup.profile.repertoire import worst_branch
from zugup.profile.weaknesses import cached_report_data
from zugup.puzzles.exercises import available
from zugup.storage.db import done_checks

EXERCISE_GOAL = 10
GAME_GOAL = 5


def week_start(now):
    now = now.astimezone(timezone.utc)
    return (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")


def attempts_since(conn, speed, since):
    return conn.execute(
        "SELECT COUNT(*) FROM attempts a JOIN moves m ON m.id = a.move_id JOIN games g ON g.id = m.game_id "
        "WHERE g.speed = ? AND a.attempted_at >= ?",
        (speed, since),
    ).fetchone()[0]


def games_since(conn, speed, since):
    return conn.execute(
        "SELECT COUNT(*) FROM games WHERE speed = ? AND played_at >= ?", (speed, since)
    ).fetchone()[0]


def auto_task(key, title, detail, target, progress):
    return {"key": key, "kind": "auto", "title": title, "detail": detail, "target": target,
            "progress": min(progress, target), "done": progress >= target}


def manual_task(key, title, detail, checked):
    return {"key": key, "kind": "manual", "title": title, "detail": detail, "target": None,
            "progress": None, "done": key in checked}


def build_plan(conn, speed, now, sections=None, t=None):
    t = t or translator()
    week = week_start(now)
    since = f"{week}T00:00:00Z"
    label = SPEED_LABELS[speed]
    sections = cached_report_data(conn) if sections is None else sections
    section = next((s for s in sections if s["speed"] == speed), None)
    plan = {"week": week, "speed": speed, "tasks": [], "advice": ""}
    if section is None:
        return plan
    checked = done_checks(conn, week, speed)
    done_attempts = attempts_since(conn, speed, since)
    goal = min(EXERCISE_GOAL, len(available(conn, [speed])) + done_attempts)
    if goal:
        plan["tasks"].append(auto_task(
            "exercises", t("plan.exercises", count=goal, speed=label), t("plan.exercises_detail"), goal, done_attempts,
        ))
    focus = focus_axis(section["radar"])
    if focus:
        plan["tasks"].append(manual_task(
            f"axis:{focus['key']}", t("plan.axis", axis=t(f"axis.{focus['key']}")), t(f"tip.{focus['key']}"), checked,
        ))
    branch = worst_branch(conn, speed)
    if branch:
        plan["tasks"].append(manual_task(
            f"opening:{branch['key']}", t("plan.line", line=branch["line"]),
            t("plan.line_detail", color=t(f"color.with.{branch['color']}")), checked,
        ))
    plan["tasks"].append(auto_task(
        "games", t("plan.games", count=GAME_GOAL, speed=label), t("plan.games_detail"),
        GAME_GOAL, games_since(conn, speed, since),
    ))
    plan["advice"] = generate_advice({
        "speed": speed, "games": section["games"], "serious_rate": section["serious_rate"],
        "axes": section["radar"], "branch": branch,
    }, t)
    return plan
