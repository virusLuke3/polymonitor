"""NBA alerts timed by ESPN plays, using the same game detail as the scoreboard."""

from datetime import datetime, timedelta, timezone

from .models import MessageCandidate, source_clock


NBA = "nba-scoreboard"
BEIJING = timezone(timedelta(hours=8))
TEAM_STATS = (
    ("fieldGoalPct", "投篮", "%"), ("threePointFieldGoalPct", "三分", "%"),
    ("freeThrowPct", "罚球", "%"), ("totalRebounds", "篮板", ""),
    ("assists", "助攻", ""), ("steals", "抢断", ""), ("blocks", "盖帽", ""),
    ("totalTurnovers", "失误", ""), ("fastBreakPoints", "快攻得分", ""),
    ("pointsInPaint", "内线得分", ""),
)


def _period(play):
    return (play.get("period") or {}).get("number", 0)


def _score(play):
    away, home = (play.get(key) for key in ("awayScore", "homeScore"))
    if all(type(value) is int and value >= 0 for value in (away, home)):
        return away, home
    return None


def _clock(play):
    return (play.get("clock") or {}).get("displayValue") or ""


def _late(play):
    score = _score(play)
    if _period(play) < 4 or not play.get("scoringPlay") or score is None or abs(score[0] - score[1]) > 5:
        return False
    minutes, colon, seconds = _clock(play).partition(":")
    try:
        remaining = 60 * int(minutes) + float(seconds) if colon else float(minutes)
    except ValueError:
        return False
    return 0 < remaining <= 120


def _milestones(plays, completed):
    if completed:
        for play in reversed(plays):
            kind = (play.get("type") or {}).get("text")
            if kind == "End Game" or (kind == "End Period" and _period(play) >= 4):
                yield "final", "完赛", play
                return
        return

    seen_periods = set()
    close = False
    for play in plays:
        period = _period(play)
        if not period:
            continue
        if period not in seen_periods:
            seen_periods.add(period)
            if period == 1:
                yield "start", "开赛", play
            elif period > 4:
                yield f"overtime-{period}", f"第 {period - 4} 个加时", play
        kind = (play.get("type") or {}).get("text")
        if kind == "End Period" and period in (1, 2, 3):
            label = "半场" if period == 2 else f"第 {period} 节结束"
            yield f"end-{period}", label, play
        if not close and _late(play):
            close = True
            yield "close", "最后两分钟 · 分差 5 分以内", play


def _team_lines(summary, sides):
    box = summary.get("boxscore") or {}
    data = {
        str(team["team"]["id"]): {stat["name"]: stat.get("displayValue") for stat in team.get("statistics", ())}
        for team in box.get("teams") or ()
    }
    table = [data.get(str(side["id"]), {}) for side in sides]
    return " · ".join(
        f"{label} {table[0][key]}{unit}/{table[1][key]}{unit}"
        for key, label, unit in TEAM_STATS if all(team.get(key) not in (None, "", "--", "-") for team in table)
    )


def _leaders(summary, sides):
    data = {str(team["team"]["id"]): team.get("leaders", ()) for team in summary.get("leaders") or ()}
    names = {"points": "分", "rebounds": "篮板", "assists": "助攻"}
    for side in sides:
        stats = []
        for group in data.get(str(side["id"]), ()):
            if group.get("name") not in names or not group.get("leaders"):
                continue
            leader = group["leaders"][0]
            name = (leader.get("athlete") or {}).get("displayName")
            value = leader.get("displayValue")
            if name and value is not None:
                stats.append(f"{name} {value} {names[group['name']]}")
        if stats:
            yield f"{side['team']['abbreviation']} · {' / '.join(stats)}"


def _starters(summary):
    for team in (summary.get("boxscore") or {}).get("players") or ():
        names = [row.get("athlete", {}).get("displayName") for group in team.get("statistics") or ()
                 for row in group.get("athletes") or () if row.get("starter")]
        if starters := " / ".join(dict.fromkeys(name for name in names if name)):
            yield f"{team['team']['abbreviation']} 首发 · {starters}"


def format_nba_game_update(detail, *, after, now, max_age, previous):
    if detail.get("status") != "ok" or not detail.get("summary"):
        return None
    summary = detail["summary"]
    game_id = str(detail.get("eventId", ""))
    header = summary.get("header") or {}
    if not game_id.isdigit() or str(header.get("id")) != game_id:
        return None
    competition = next(iter(header.get("competitions") or ()), {})
    phase = (competition.get("status") or {}).get("type") or {}
    if phase.get("state") not in ("in", "post"):
        return None
    sides = {row.get("homeAway"): row for row in competition.get("competitors") or ()}
    if "away" not in sides or "home" not in sides:
        return None
    away, home = sides["away"], sides["home"]
    plays = [play for play in summary.get("plays") or () if source_clock(play, "wallclock") is not None]
    events = []
    for key, title, play in _milestones(plays, phase.get("completed") is True):
        stamp = source_clock(play, "wallclock")
        if max(after, now - max_age) < stamp <= now and stamp >= previous.get("at", 0) and key not in previous.get("keys", ()):
            if _score(play) is not None:
                events.append((stamp, key, title, play))
    if not events:
        return None
    stamp, key, title, play = max(reversed(events), key=lambda event: event[0])
    score = _score(play)
    lines = [
        f"🏀 NBA · {title}",
        f"{away['team']['displayName']} {score[0]}–{score[1]} {home['team']['displayName']}",
    ]
    if key == "final" or key.startswith("end-"):
        last_score = next((row for row in reversed(plays) if _period(row) == _period(play)
                           and row.get("scoringPlay") and row.get("text")), None)
        if last_score:
            lines.append(f"本节最后得分 · {_clock(last_score)} · {last_score['text']}")
    elif play.get("text"):
        lines.append(f"{_clock(play)} · {play['text']}" if _clock(play) else play["text"])
    if key != "final":
        probability = next((row.get("homeWinPercentage") for row in summary.get("winprobability") or ()
                            if str(row.get("playId")) == str(play.get("id"))), None)
        if isinstance(probability, (float, int)) and 0 <= probability <= 1:
            lines.append(f"ESPN {home['team']['abbreviation']} 当时胜率 {probability:.1%}")

    teams = (away, home)
    latest = plays[-1]
    latest_score = _score(latest)
    latest_stamp = source_clock(latest, "wallclock")
    if key != "final" and latest_score and latest_stamp > stamp:
        period = _period(latest)
        stage = f"第 {period} 节" if period <= 4 else f"OT{period - 4}"
        recent = datetime.fromtimestamp(latest_stamp, BEIJING).strftime("%H:%M:%S")
        lines.append(f"最新赛况 · {stage} {_clock(latest)} · {latest_score[0]}–{latest_score[1]} · 北京时间 {recent}")
        if latest.get("text") and latest["text"] != play.get("text"):
            lines.append(f"最近回合 · {latest['text']}")
    periods = [" / ".join(str(row["displayValue"]) for row in team.get("linescores", ())
                          if row.get("displayValue") is not None) for team in teams]
    if all(periods):
        lines.append(f"分节得分 · {away['team']['abbreviation']} {periods[0]}｜{home['team']['abbreviation']} {periods[1]}")
    if key == "start":
        lines.extend(_starters(summary))
    else:
        if stats := _team_lines(summary, teams):
            lines.append(f"球队统计（客/主）· {stats}")
        lines.extend(_leaders(summary, teams))
    broadcasts = summary.get("broadcasts") or ()
    venue = ((summary.get("gameInfo") or {}).get("venue") or {}).get("fullName")
    names = list(dict.fromkeys(str(row["media"]["shortName"]) for row in broadcasts if (row.get("media") or {}).get("shortName")))
    if facts := " · ".join(part for part in (venue, " / ".join(names[:3])) if part):
        lines.append(facts)
    lines += [f"ESPN 事件时间 · 北京时间 {datetime.fromtimestamp(stamp, BEIJING):%m-%d %H:%M:%S}",
              f"ESPN Gamecast · https://www.espn.com/nba/game?gameId={game_id}"]
    return MessageCandidate(
        topic="nba", dedupe_key=f"nba-game:{game_id}:{key}", text="\n".join(lines),
        observed_at=stamp, metadata={"panel": NBA, "game": game_id, "milestone": key},
    )
