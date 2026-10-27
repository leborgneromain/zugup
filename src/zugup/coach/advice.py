from zugup.i18n import translator

SPEED_LABELS = {"bullet": "Bullet", "blitz": "Blitz", "rapid": "Rapid"}


def gap(axis):
    if axis["score"] is None or axis.get("peer_score") is None:
        return None
    return axis["score"] - axis["peer_score"]


def focus_axis(axes):
    scored = [a for a in axes if a["score"] is not None]
    compared = [a for a in scored if gap(a) is not None]
    if compared:
        return min(compared, key=gap)
    return min(scored, key=lambda a: a["score"]) if scored else None


def strongest_axis(axes):
    compared = [a for a in axes if gap(a) is not None and gap(a) >= 1]
    return max(compared, key=gap) if compared else None


def axis_sentence(t, axis, prefix):
    params = {"prefix": t(prefix), "label": t(f"axis.{axis['key']}"), "score": t.percent(axis["score"])}
    if axis.get("peer_score") is not None:
        return t("advice.axis_peer", peer=t.percent(axis["peer_score"]), **params)
    return t("advice.axis", **params)


def generate_advice(profile, t=None):
    t = t or translator()
    lines = [t(
        "advice.summary", count=profile["games"], speed=SPEED_LABELS[profile["speed"]], games=profile["games"],
        rate=t.percent(profile["serious_rate"] * 100),
    )]
    focus = focus_axis(profile["axes"])
    if focus:
        lines.append(f"{axis_sentence(t, focus, 'advice.focus')} {t('tip.' + focus['key'])}")
    strong = strongest_axis(profile["axes"])
    if strong and strong is not focus:
        lines.append(axis_sentence(t, strong, "advice.strong"))
    branch = profile.get("branch")
    if branch:
        lines.append(t(
            "advice.branch", color=t(f"color.with.{branch['color']}"), line=branch["line"], errors=branch["errors"],
            games=branch["games"], rate=t.percent(branch["rate"] * 100), baseline=t.percent(branch["baseline"] * 100),
        ))
    return "\n".join(lines)
