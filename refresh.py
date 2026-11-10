#!/usr/bin/env python3
"""Refresh the Sagarin ratings page data from sagarin.com.

Parses Jeff Sagarin's fixed-width ratings file, rebuilds the DATA blob
embedded in index.html, and splices it in. Usage:

  refresh.py           dry run: parse and compare against the embedded data
  refresh.py --write   splice the fresh data into index.html

Prints a JSON summary line. Exits non-zero if the parse fails validation,
so callers (the Sunday cron) stop instead of pushing a broken page.

HOW TO EDIT THIS FILE BY HAND (Brandon's notes):
- The values you would most likely change live in the SETTINGS block
  right below the imports: SOURCE (where the ratings come from) and
  PAGE (which local page file gets updated).
- If Sagarin ever changes his file format, the breakage will almost
  certainly be in one of the five regexes under PARSING PATTERNS. Each
  regex carries a numbered map of its capture groups, and parse() reads
  the groups by those same numbers (g[0], g[1], ...), so keep the map
  and the code in step if you touch a pattern.
- Week-over-week trends (added 2026-11-10): every --write run also
  records the edition's ratings into snapshots.json (one entry per
  edition, last 8 kept). build_trends() compares the fresh parse
  against those snapshots and adds a "trends" key to the DATA blob:
  per team, last week's rating ("prev") and the last few weekly
  ratings ("spark", ending at the current one). The page renders an
  arrow, a signed delta, and a sparkline from it. Dry runs never
  record snapshots.
- The sanity checks in parse() (266 teams, a conference count in the
  20 to 32 range, at least one prediction) are deliberate tripwires. The
  team count stays exact, but the conference count is a range on purpose:
  Sagarin adds groupings as teams move (Week 8 of 2026 added I-AA IND.
  as the 27th conference). If a future season really has a different
  team count, update the expected number there AND in the check, do not
  just delete the check: it is what stops the Sunday cron from pushing
  a half-parsed page.
"""
import json
import re
import sys
import urllib.request

# ---------------------------------------------------------------------------
# SETTINGS: the two values a manual edit would most likely change.
# SOURCE is Sagarin's published ratings file (the single source of truth).
# PAGE is the local master copy of the site; the Sunday cron pushes this
# file's contents to GitHub (repo bparish0619-cyber/cfbsaga), which
# auto-deploys https://cfbsaga.netlify.app.
# ---------------------------------------------------------------------------
SOURCE = "http://sagarin.com/sports/cfsend.htm"
PAGE = "/home/hatch/workspace/sagarin-site/index.html"
# SNAPSHOTS is the trend history: one ratings map per edition, used to
# build the week-over-week arrows and sparkline data on the page.
SNAPSHOTS = "/home/hatch/workspace/sagarin-site/snapshots.json"

# ---------------------------------------------------------------------------
# PARSING PATTERNS: one regex per line type in Sagarin's file.
# His file is fixed-width text, so each pattern walks a line left to
# right. The numbered comments are the capture-group indexes used later
# as g[0], g[1], ... in parse(). Groups are 0-based in the code because
# t.groups() / c.groups() / p.groups() return a tuple starting at 0.
# ---------------------------------------------------------------------------

# One team line, for example:
#   7 LSU                    A =  90.87  5  1  74.89( 16)  0  1 |  1  2 | ...
# Groups: 0=rank, 1=team name, 2=division (A or AA), 3=overall rating,
# 4=wins, 5=losses, 6=schedule rating, 7=schedule rank, 8=wins vs top 10,
# 9=losses vs top 10, 10=wins vs top 30, 11=losses vs top 30,
# 12=Predictor rating, 13=Predictor rank, 14=Golden Mean rating,
# 15=Golden Mean rank, 16=Recent rating, 17=Recent rank,
# 18=Strong Recent rating, 19=Strong Recent rank, 20=conference name
# (the conference still carries a trailing "(A)" or "(AA)" marker here;
# parse() strips it when building the team record).
TEAM_RE = re.compile(
    r"^\s*(\d+)\s+(.+?)\s+(AA|A)\s+=\s+(-?[\d.]+)\s+(\d+)\s+(\d+)\s+"
    r"(-?[\d.]+)\(\s*(\d+)\)\s+(\d+)\s+(\d+)\s*\|\s*(\d+)\s+(\d+)\s*\|\s*"
    r"(-?[\d.]+)\s+(\d+)\s*\|\s*(-?[\d.]+)\s+(\d+)\s*\|\s*"
    r"(-?[\d.]+)\s+(\d+)\s*\|\s*(-?[\d.]+)\s+(\d+)\s+(.+?)\s*$"
)

# One conference-average line.
# Groups: 0=rank, 1=conference name, 2=division, 3=central mean,
# 4=simple average, 5=simple average rank, 6=number of teams,
# 7=rating a .500 team would need against this conference (win50),
# 8=win50 rank.
CONF_RE = re.compile(
    r"^\s*(\d+)\s+(.+?)\s+\((AA|A)\)\s*=\s+(-?[\d.]+)\s+(-?[\d.]+)\s*"
    r"\(\s*(\d+)\)\s+(\d+)\s+(-?[\d.]+)\s*\(\s*(\d+)\)"
)

# One prediction line from the Predictions_with_Totals_and_Moneylines
# section. The "@" marker sits in front of whichever team is at home.
# Groups: 0="@" if the FAVORITE is home (else None), 1=favorite name,
# 2=margin by overall Rating, 3=margin by Predictor, 4=margin by
# Golden Mean, 5=margin by Recent, 6=margin by Strong Recent,
# 7="@" if the UNDERDOG is home (else None), 8=underdog name,
# 9=favorite's moneyline, 10=favorite's win percent,
# 11=projected home score, 12=projected away score, 13=projected total,
# 14=underdog's win percent, 15=underdog's moneyline.
# NOTE: parse() only uses groups 0-13; groups 14 and 15 (the underdog's
# win percent and moneyline) are captured by the pattern but not stored,
# because the page derives the underdog side from the favorite's numbers.
PRED_RE = re.compile(
    r"^\s*\d+\s+(@\s+)?(.+?)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+"
    r"(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(@\s+)?(.+?)\s+(-?\d+)\s+(\d+)%\s+"
    r"(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)%\s+(-?\d+)\s*$"
)

# The single "HOME ADVANTAGE=[..] [..] [..] [..] [..]" line.
# Groups, in order: 0=overall Rating, 1=Predictor, 2=Golden Mean,
# 3=Recent, 4=Strong Recent. The page's matchup predictor subtracts the
# matching value when a team is at home, per Sagarin's published method.
HOME_RE = re.compile(
    r"HOME ADVANTAGE=\[\s*([\d.]+)\]\s+\[\s*([\d.]+)\]\s+\[\s*([\d.]+)\]\s+"
    r"\[\s*([\d.]+)\]\s+\[\s*([\d.]+)\]"
)

# The edition header line, for example:
#   2026 COLLEGE FOOTBALL through results of OCTOBER 17 SATURDAY - WEEK 7
# Groups: 0=year, 1=month (all caps), 2=day of month, 3=week number.
# re.M lets ^ match at the start of any line, not just the file start.
EDITION_RE = re.compile(
    r"^(\d{4}) COLLEGE FOOTBALL through results of ([A-Z]+) (\d+) [A-Z]+ - WEEK (\d+)",
    re.M,
)


def f(x):
    # Short helper: every rating in Sagarin's file is text; the page
    # stores them as numbers, so parse() routes them all through float().
    return float(x)


def parse(text):
    """Turn Sagarin's raw file text into the DATA dict the page embeds.

    Raises ValueError on anything unexpected. Callers rely on that: a
    raised error means "format changed or download broke, push nothing".
    """
    # --- Edition header: builds the human label shown on the page. ---
    m = EDITION_RE.search(text)
    if not m:
        raise ValueError("edition line not found")
    year, month, day, week = m.group(1), m.group(2).title(), m.group(3), m.group(4)
    raw_edition = m.group(0)
    edition_label = f"Through games of {month} {int(day)}, {year} · Week {week}"

    # --- Home advantage values, one per rating system. ---
    hm = HOME_RE.search(text)
    if not hm:
        raise ValueError("home advantage line not found")
    home = {
        "rating": f(hm.group(1)),
        "predictor": f(hm.group(2)),
        "goldenMean": f(hm.group(3)),
        "recent": f(hm.group(4)),
        "strongRecent": f(hm.group(5)),
    }

    # --- Teams: keyed by rank so the repeated listing later in his
    # file (part 3 repeats part 1) cannot create duplicates. ---
    teams_by_rank = {}
    for line in text.splitlines():
        t = TEAM_RE.match(line)
        if not t:
            continue
        g = t.groups()
        rank = int(g[0])
        if rank in teams_by_rank:
            continue  # part 3 repeats part 1; first copy wins
        teams_by_rank[rank] = {
            "rank": rank,
            "name": g[1].strip(),
            "division": g[2],
            "rating": f(g[3]),
            "wins": int(g[4]),
            "losses": int(g[5]),
            "schedl": f(g[6]),
            "schedlRank": int(g[7]),
            "vsTop10W": int(g[8]),
            "vsTop10L": int(g[9]),
            "vsTop30W": int(g[10]),
            "vsTop30L": int(g[11]),
            "predictor": f(g[12]),
            "predictorRank": int(g[13]),
            "goldenMean": f(g[14]),
            "goldenMeanRank": int(g[15]),
            "recent": f(g[16]),
            "recentRank": int(g[17]),
            "strongRecent": f(g[18]),
            "strongRecentRank": int(g[19]),
            # Strip the trailing "(A)" / "(AA)" division marker from
            # the conference name; the page displays the clean name.
            "conference": re.sub(r"\s*\((?:AA|A)\)\s*$", "", g[20]).strip(),
        }
    teams = [teams_by_rank[r] for r in sorted(teams_by_rank)]
    # Tripwire (see the note at the top of this file): a complete parse
    # must yield every rank 1..266 exactly once, or something changed.
    if len(teams) != 266 or [t["rank"] for t in teams] != list(range(1, 267)):
        raise ValueError(f"team parse failed: {len(teams)} teams")

    # --- Conferences: keyed by name for the same de-dupe reason.
    # Lines whose name starts with "___" are his unrated placeholder
    # row and are skipped on purpose. ---
    confs_by_name = {}
    for line in text.splitlines():
        c = CONF_RE.match(line)
        if not c:
            continue
        g = c.groups()
        name = g[1].strip()
        if name.startswith("___") or name in confs_by_name:
            continue
        confs_by_name[name] = {
            "rank": int(g[0]),
            "name": name,
            "division": g[2],
            "centralMean": f(g[3]),
            "simpleAverage": f(g[4]),
            "simpleAverageRank": int(g[5]),
            "teamCount": int(g[6]),
            "win50": f(g[7]),
            "win50Rank": int(g[8]),
        }
    conferences = sorted(confs_by_name.values(), key=lambda c: c["rank"])
    # Conference count is a sanity RANGE (20 to 32), not an exact number:
    # Sagarin adds or drops groupings as teams move. Week 8 of 2026 added
    # I-AA IND. as the 27th conference, which an exact "26" check rejected.
    # The range still trips if the conference section fails to parse.
    # Brandon: widen this range only if the real count legitimately
    # grows past it; the team count check above stays exact on purpose.
    if not (20 <= len(conferences) <= 32):
        raise ValueError(f"conference parse failed: {len(conferences)} conferences")

    # --- Predictions: only the basic set. Scanning starts at the
    # section's HTML anchor name and stops at the EXPERIMENTAL heading,
    # because the experimental set that follows uses different math
    # and is not part of the page. ---
    predictions = []
    in_preds = False
    for line in text.splitlines():
        if 'name="Predictions_with_Totals_and_Moneylines"' in line:
            in_preds = True
            continue
        if in_preds and line.startswith("EXPERIMENTAL"):
            break  # the basic set ends here; the experimental set follows
        if not in_preds:
            continue
        p = PRED_RE.match(line)
        if not p:
            continue
        g = p.groups()
        favorite = g[1].strip()
        underdog = g[8].strip()
        # Home team logic: the "@" group in front of a name marks that
        # team as home. If neither name carries one (neutral site), the
        # favorite is stored as homeTeam, matching how Sagarin prints it.
        home_team = favorite if g[0] else (underdog if g[7] else favorite)
        predictions.append(
            {
                "favorite": favorite,
                "underdog": underdog,
                "homeTeam": home_team,
                "ratingMargin": f(g[2]),
                "predictorMargin": f(g[3]),
                "goldenMargin": f(g[4]),
                "recentMargin": f(g[5]),
                "strongMargin": f(g[6]),
                "moneyline": int(g[9]),
                "winPct": int(g[10]),
                "homeScore": f(g[11]),
                "awayScore": f(g[12]),
                "total": f(g[13]),
            }
        )
    if not predictions:
        raise ValueError("no predictions parsed")

    # This dict's shape is exactly the DATA blob embedded in index.html.
    # Renaming a key here means renaming it in the page's JavaScript too.
    return {
        "editionLabel": edition_label,
        "rawEdition": raw_edition,
        "homeAdvantage": home,
        "teams": teams,
        "conferences": conferences,
        "predictions": predictions,
    }


def load_snapshots():
    """Read the trend history file. Any problem (missing file, bad
    JSON) returns an empty list: trends are a garnish, and a broken
    history must never block the ratings refresh itself."""
    try:
        with open(SNAPSHOTS, encoding="utf-8") as fh:
            snaps = json.load(fh)
        return snaps if isinstance(snaps, list) else []
    except Exception:
        return []


def build_trends(data, snaps):
    """Compare the fresh parse against earlier snapshots.

    Returns {team name: {"prev": rating, "spark": [ratings]}} where
    prev is the rating in the newest snapshot from an EARLIER edition
    and spark is that team's rating in the last few earlier snapshots
    (oldest first) with the current rating appended. Teams missing
    from the earlier snapshot get no entry and render without a trend.
    """
    earlier = [s for s in snaps if s.get("edition") != data["rawEdition"]]
    if not earlier:
        return {}
    prev_map = earlier[-1].get("ratings", {})
    trends = {}
    for t in data["teams"]:
        name = t["name"]
        if name not in prev_map:
            continue
        spark = []
        for s in earlier[-5:]:
            r = s.get("ratings", {}).get(name)
            if r is not None:
                spark.append(r)
        spark.append(t["rating"])
        trends[name] = {"prev": prev_map[name], "spark": spark}
    return trends


def record_snapshot(data, snaps):
    """Return the snapshot list with this edition's ratings recorded:
    one entry per edition (re-recording an edition replaces it),
    oldest first, capped at the last 8 editions."""
    entry = {
        "edition": data["rawEdition"],
        "label": data["editionLabel"],
        "ratings": {t["name"]: t["rating"] for t in data["teams"]},
    }
    snaps = [s for s in snaps if s.get("edition") != entry["edition"]]
    snaps.append(entry)
    return snaps[-8:]


def find_blob(html):
    """Locate the embedded DATA object inside index.html.

    Returns (start, end) character offsets of the JSON object that
    holds "editionLabel". The scan counts braces while respecting
    quoted strings, so braces inside team names or text cannot throw
    the depth count off.
    """
    i = html.find('"homeAdvantage"')
    if i < 0:
        raise ValueError("DATA blob not found in page")
    start = html.rfind("{", 0, html.rfind('"editionLabel"', 0, i) + 1)
    start = html.rfind("{\n", 0, i)
    # Robust: walk back to the '{' that opens the object holding editionLabel
    # (The two assignments above are earlier attempts kept in place;
    # this last one is the value actually used.)
    j = html.find('"editionLabel"')
    start = html.rfind("{", 0, j)
    depth = 0
    in_str = False
    esc = False
    for k in range(start, len(html)):
        c = html[k]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return start, k
    raise ValueError("DATA blob end not found")


def main():
    # No argument = dry run (report only). --write = actually splice
    # the fresh DATA blob into PAGE. The Sunday cron runs a dry run
    # first and only calls --write when the edition has changed.
    write = "--write" in sys.argv
    req = urllib.request.Request(SOURCE, headers={"User-Agent": "Mozilla/5.0"})
    text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    data = parse(text)
    snaps = load_snapshots()
    data["trends"] = build_trends(data, snaps)

    html = open(PAGE, encoding="utf-8").read()
    start, end = find_blob(html)
    current = json.loads(html[start : end + 1])
    changed = current != data

    if write and changed:
        blob = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        html = html[:start] + blob + html[end + 1 :]
        open(PAGE, "w", encoding="utf-8").write(html)
        # Record this edition for future trend comparisons. Only on a
        # real write of changed data, so dry runs and no-change runs
        # never pollute the history.
        with open(SNAPSHOTS, "w", encoding="utf-8") as fh:
            json.dump(record_snapshot(data, snaps), fh, ensure_ascii=False)

    # One-line JSON summary on stdout. The cron reads the "changed",
    # "top1" and "lsu" fields for its report to the Projects chat, so
    # keep those key names stable if you edit this block.
    lsu = next((t for t in data["teams"] if t["name"] == "LSU"), {})
    top = data["teams"][0]
    print(
        json.dumps(
            {
                "edition": data["editionLabel"],
                "rawEdition": data["rawEdition"],
                "teams": len(data["teams"]),
                "conferences": len(data["conferences"]),
                "predictions": len(data["predictions"]),
                "top1": f"{top['name']} {top['rating']}",
                "lsu": f"#{lsu.get('rank')} {lsu.get('rating')}",
                "changed": changed,
                "written": bool(write and changed),
                "trends": len(data["trends"]),
            }
        )
    )


if __name__ == "__main__":
    main()
