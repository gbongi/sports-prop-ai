from flask import Flask, render_template, request, jsonify
import sqlite3
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
from pathlib import Path
import requests
import re
import unicodedata

from main import get_player_games, get_stat, predict_prop_v1, CURRENT_SEASON, DATABASE, get_wnba_injuries, parse_injuries, get_wnba_injuries, parse_injuries
from mlb_model import (
    HITTER_PROPS,
    PITCHER_PROPS,
    mlb_teams,
    mlb_team_roster,
    mlb_pregame_game_context,
    analyze_mlb_verified,
    clear_mlb_api_cache,
    set_mlb_api_cache,
)

app = Flask(__name__)



# ============================================================
# LATEST SCANNER SNAPSHOTS
# ============================================================

SCANNER_SNAPSHOT_DATABASE = (
    Path(__file__).resolve().parent
    / "database"
    / "scanner_snapshots.db"
)


def scanner_snapshot_connection():
    SCANNER_SNAPSHOT_DATABASE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    con = sqlite3.connect(
        SCANNER_SNAPSHOT_DATABASE
    )

    con.row_factory = sqlite3.Row

    return con


def init_scanner_snapshot_database():
    con = scanner_snapshot_connection()

    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS latest_scans (
                sport TEXT PRIMARY KEY,
                scanned_at TEXT NOT NULL,
                scan_date TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )

        con.commit()

    finally:
        con.close()


def save_latest_scanner_snapshot(sport, scan):
    sport = str(
        sport or ""
    ).strip().upper()

    if sport not in {"MLB", "WNBA"}:
        raise ValueError(
            "Unsupported scanner snapshot sport"
        )

    now = datetime.now()

    payload = dict(scan or {})

    payload["sport"] = sport
    payload["snapshot_scanned_at"] = (
        now.isoformat(timespec="seconds")
    )
    payload["snapshot_scan_date"] = (
        now.date().isoformat()
    )

    con = scanner_snapshot_connection()

    try:
        con.execute(
            """
            INSERT INTO latest_scans (
                sport,
                scanned_at,
                scan_date,
                payload
            )
            VALUES (?, ?, ?, ?)

            ON CONFLICT(sport)
            DO UPDATE SET
                scanned_at=excluded.scanned_at,
                scan_date=excluded.scan_date,
                payload=excluded.payload
            """,
            (
                sport,
                payload["snapshot_scanned_at"],
                payload["snapshot_scan_date"],
                json.dumps(
                    payload,
                    default=str
                ),
            ),
        )

        con.commit()

    finally:
        con.close()

    return payload


def load_latest_scanner_snapshot(sport):
    sport = str(
        sport or ""
    ).strip().upper()

    if sport not in {"MLB", "WNBA"}:
        return None

    con = scanner_snapshot_connection()

    try:
        row = con.execute(
            """
            SELECT
                sport,
                scanned_at,
                scan_date,
                payload
            FROM latest_scans
            WHERE sport = ?
            """,
            (sport,),
        ).fetchone()

    finally:
        con.close()

    if row is None:
        return None

    try:
        payload = json.loads(
            row["payload"]
        )
    except Exception:
        return None

    today = date.today().isoformat()

    stale = (
        str(row["scan_date"]) != today
    )

    payload["snapshot_scanned_at"] = (
        row["scanned_at"]
    )

    payload["snapshot_scan_date"] = (
        row["scan_date"]
    )

    payload["snapshot_restored"] = True
    payload["snapshot_stale"] = stale

    return payload


init_scanner_snapshot_database()


# ============================================================
# PREDICTION TRACKING
# ============================================================

TRACKING_DATABASE = (
    Path(__file__).resolve().parent
    / "database"
    / "prediction_tracking.db"
)


def tracking_connection():
    TRACKING_DATABASE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    con = sqlite3.connect(TRACKING_DATABASE)
    con.row_factory = sqlite3.Row

    return con


def init_tracking_database():
    con = tracking_connection()

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            saved_at TEXT NOT NULL,

            sport TEXT NOT NULL,
            projection_id TEXT,

            game_id TEXT,
            game_start_time TEXT,

            player TEXT NOT NULL,
            player_id TEXT,
            player_type TEXT,

            team TEXT,
            opponent TEXT,

            pp_prop TEXT NOT NULL,
            model_prop TEXT,
            pp_line REAL NOT NULL,

            projection REAL,

            p_more REAL,
            p_less REAL,
            strongest_probability REAL,

            raw_lean TEXT,
            raw_confidence TEXT,

            final_lean TEXT,
            final_confidence TEXT,

            model_edge REAL,

            market_available INTEGER DEFAULT 0,
            market_lean TEXT,
            market_probability REAL,
            market_strength TEXT,
            market_books INTEGER,
            market_dispersion REAL,
            market_check TEXT,
            market_agreement INTEGER,

            scan_stage TEXT,
            scanner_status TEXT,
            qualifies INTEGER DEFAULT 0,
            final_pick INTEGER DEFAULT 0,

            actual_value REAL,
            actual_result TEXT,
            graded_at TEXT,

            UNIQUE (
                sport,
                game_id,
                player,
                pp_prop,
                pp_line
            )
        )
        """
    )

    con.commit()
    con.close()


init_tracking_database()


WNBA_PROPS = ["points", "rebounds", "assists", "3pm", "pra", "ra", "pa", "pr", "minutes"]

ESPN_WNBA_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
)
MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"


# ----------------------------
# WNBA schedule helpers
# ----------------------------

def espn_wnba_schedule(game_date):
    """Return ESPN's WNBA schedule for YYYY-MM-DD."""
    datetime.strptime(game_date, "%Y-%m-%d")

    r = requests.get(
        ESPN_WNBA_SCOREBOARD,
        params={"dates": game_date.replace("-", ""), "limit": 100},
        timeout=20,
    )
    r.raise_for_status()

    games = []

    for event in r.json().get("events", []):
        competitions = event.get("competitions") or []
        if not competitions:
            continue

        competitors = competitions[0].get("competitors") or []
        home = None
        away = None

        for c in competitors:
            t = c.get("team") or {}
            item = {
                "id": t.get("id"),
                "name": t.get("displayName") or t.get("name") or t.get("abbreviation"),
                "abbreviation": t.get("abbreviation"),
            }

            if c.get("homeAway") == "home":
                home = item
            elif c.get("homeAway") == "away":
                away = item

        if not home or not away:
            continue

        status = (event.get("status") or {}).get("type") or {}

        games.append({
            "game_id": str(event.get("id") or ""),
            "date": game_date,
            "status": status.get("description") or "Unknown",
            "completed": bool(status.get("completed", False)),
            "home": home,
            "away": away,
        })

    return games


def wnba_teams():
    con = sqlite3.connect(DATABASE)
    con.row_factory = sqlite3.Row

    rows = con.execute(
        """
        SELECT DISTINCT team
        FROM player_games
        WHERE season=? AND team IS NOT NULL
        ORDER BY team
        """,
        (CURRENT_SEASON,),
    ).fetchall()

    con.close()

    return [
        {"id": r["team"], "name": r["team"], "abbreviation": r["team"]}
        for r in rows
    ]


def wnba_roster(team):
    con = sqlite3.connect(DATABASE)
    con.row_factory = sqlite3.Row

    rows = con.execute(
        """
        SELECT player, MAX(date) last_date
        FROM player_games
        WHERE season=? AND UPPER(team)=UPPER(?)
        GROUP BY player
        ORDER BY player
        """,
        (CURRENT_SEASON, team),
    ).fetchall()

    con.close()

    return [
        {"id": r["player"], "name": r["player"], "position": ""}
        for r in rows
    ]


def build_wnba_history(games, prop, opponent=None):
    """Last 7 for selected prop + current-season games vs selected opponent."""
    ordered = sorted(games, key=lambda g: g["date"] or "", reverse=True)

    last7 = []

    for game in ordered:
        value = get_stat(game, prop)

        if value is None:
            continue

        last7.append({
            "date": game["date"],
            "opponent": game["opponent"],
            "home_away": game["home_away"],
            "value": round(float(value), 1),
        })

        if len(last7) == 7:
            break

    matchup = []

    if opponent:
        opp = opponent.upper()

        for game in ordered:
            if str(game["opponent"] or "").upper() != opp:
                continue

            value = get_stat(game, prop)

            if value is None:
                continue

            matchup.append({
                "date": game["date"],
                "value": round(float(value), 1),
            })

    matchup_average = (
        round(sum(x["value"] for x in matchup) / len(matchup), 1)
        if matchup
        else None
    )

    return {
        "last7": last7,
        "matchup_games": matchup,
        "matchup_average": matchup_average,
        "matchup_available": bool(matchup),
    }


# ----------------------------
# MLB schedule helpers
# ----------------------------


def normalize_mlb_player_name(value):
    """
    Conservative MLB name normalization.

    Handles:
      Iván Herrera -> ivan herrera
      Jazz Chisholm Jr. -> jazz chisholm jr
      punctuation / whitespace differences

    Does NOT fuzzy-match unrelated players.
    """
    if not value:
        return ""

    value = str(value).strip().lower()

    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        c for c in value
        if not unicodedata.combining(c)
    )

    value = value.replace("’", "'")

    value = re.sub(
        r"\s*\([^)]*\)\s*$",
        "",
        value,
    )

    value = re.sub(
        r"[^a-z0-9\s]",
        "",
        value,
    )

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def game_scan_stage(start_time, status=None):
    """
    Classify a game for the daily prop scanner.

    PRELIMINARY = more than 3 hours away
    MONITORING  = 1 to 3 hours away
    FINAL CHECK = less than 1 hour away
    LOCKED      = game has started / is no longer pregame
    """
    if not start_time:
        return {
            "stage": "UNKNOWN",
            "minutes_to_game": None,
            "eligible_for_best_picks": False,
        }

    try:
        start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        now = datetime.now(start.tzinfo)

        minutes = (start - now).total_seconds() / 60.0

        status_text = str(status or "").lower()

        locked_words = (
            "in progress",
            "final",
            "completed",
            "game over",
            "live",
        )

        if minutes <= 0 or any(word in status_text for word in locked_words):
            stage = "LOCKED"
            eligible = False

        elif minutes <= 60:
            stage = "FINAL CHECK"
            eligible = True

        elif minutes <= 180:
            stage = "MONITORING"
            eligible = False

        else:
            stage = "PRELIMINARY"
            eligible = False

        return {
            "stage": stage,
            "minutes_to_game": round(minutes, 1),
            "eligible_for_best_picks": eligible,
        }

    except Exception:
        return {
            "stage": "UNKNOWN",
            "minutes_to_game": None,
            "eligible_for_best_picks": False,
        }



def mlb_schedule_for_date(game_date):
    """
    Get MLB games for one date from MLB's schedule API.
    Team IDs match the MLB team IDs already used by the app.
    """
    datetime.strptime(game_date, "%Y-%m-%d")

    r = requests.get(
        MLB_SCHEDULE_URL,
        params={
            "sportId": 1,
            "date": game_date,
            "hydrate": "probablePitcher,team",
        },
        timeout=20,
    )
    r.raise_for_status()

    games = []

    for date_block in r.json().get("dates", []):
        for g in date_block.get("games", []):
            teams = g.get("teams") or {}

            away_obj = (teams.get("away") or {}).get("team") or {}
            home_obj = (teams.get("home") or {}).get("team") or {}

            away_probable = g.get("probablePitcher")
            home_probable = None

            # Depending on API response, probable pitchers can live on each side.
            away_side = teams.get("away") or {}
            home_side = teams.get("home") or {}

            away_p = away_side.get("probablePitcher") or {}
            home_p = home_side.get("probablePitcher") or {}

            if away_p:
                away_probable = away_p.get("fullName")
            else:
                away_probable = None

            if home_p:
                home_probable = home_p.get("fullName")

            # Some MLB responses expose probablePitcher only after hydration
            # through team-side data. If not posted, keep it None rather than guess.
            games.append({
                "game_id": str(g.get("gamePk") or ""),
                "date": game_date,
                "start_time": g.get("gameDate"),
                "status": ((g.get("status") or {}).get("detailedState") or "Unknown"),
                "away": {
                    "id": away_obj.get("id"),
                    "name": away_obj.get("name"),
                    "abbreviation": away_obj.get("abbreviation"),
                    "probable": away_probable,
                },
                "home": {
                    "id": home_obj.get("id"),
                    "name": home_obj.get("name"),
                    "abbreviation": home_obj.get("abbreviation"),
                    "probable": home_probable,
                },
            })

    # If the first hydration form did not expose probable pitchers, ask for
    # probablePitcher(note) as a fallback and merge by gamePk.
    if games and not any(g["away"]["probable"] or g["home"]["probable"] for g in games):
        try:
            r2 = requests.get(
                MLB_SCHEDULE_URL,
                params={
                    "sportId": 1,
                    "date": game_date,
                    "hydrate": "probablePitcher",
                },
                timeout=20,
            )
            r2.raise_for_status()

            by_id = {g["game_id"]: g for g in games}

            for date_block in r2.json().get("dates", []):
                for raw in date_block.get("games", []):
                    target = by_id.get(str(raw.get("gamePk") or ""))
                    if not target:
                        continue

                    raw_teams = raw.get("teams") or {}

                    ap = (raw_teams.get("away") or {}).get("probablePitcher") or {}
                    hp = (raw_teams.get("home") or {}).get("probablePitcher") or {}

                    if ap.get("fullName"):
                        target["away"]["probable"] = ap["fullName"]

                    if hp.get("fullName"):
                        target["home"]["probable"] = hp["fullName"]

        except requests.RequestException:
            pass

    return games


def mlb_matchup_for_team(game_date, team_id):
    team_id = str(team_id)

    for g in mlb_schedule_for_date(game_date):
        away_id = str(g["away"].get("id") or "")
        home_id = str(g["home"].get("id") or "")

        if team_id == away_id:
            return {
                "found": True,
                "game_id": g["game_id"],
                "status": g["status"],
                "team": g["away"],
                "opponent": g["home"],
                "home_away": "AWAY",
                "team_probable": g["away"].get("probable"),
                "opponent_probable": g["home"].get("probable"),
                "away": g["away"].get("name"),
                "home": g["home"].get("name"),
            }

        if team_id == home_id:
            return {
                "found": True,
                "game_id": g["game_id"],
                "status": g["status"],
                "team": g["home"],
                "opponent": g["away"],
                "home_away": "HOME",
                "team_probable": g["home"].get("probable"),
                "opponent_probable": g["away"].get("probable"),
                "away": g["away"].get("name"),
                "home": g["home"].get("name"),
            }

    return {
        "found": False,
        "message": "No MLB game found for that team on this date.",
        "team_probable": None,
        "opponent_probable": None,
    }


# ----------------------------
# MLB DAILY PROP SCANNER
# ----------------------------

from prizepicks_board import (
    get_prizepicks_board,
    get_supported_board,
    SUPPORTED_PROPS,
)

from mlb_market_bridge import (
    enrich_mlb_pp_board_with_market,
)

from propline_market import (
    compare_model_to_market,
)

from wnba_market_bridge import enrich_wnba_pp_board_with_market, WNBA_MARKET_MAP


def scan_mlb_hitter_fantasy_score(game_date, line=4.5, direction="MORE"):
    """
    Scan all active non-pitchers in MLB games on the selected date.

    This does NOT replace the normal MLB analyzer.
    It reuses analyze_mlb_verified() for every eligible hitter.
    """

    # Fresh data at the beginning of every scanner run.
    # Reuse duplicate MLB API requests only within this scan.
    clear_mlb_api_cache()
    set_mlb_api_cache(True)

    direction = str(direction or "MORE").upper()

    if direction not in ("MORE", "LESS"):
        raise ValueError("Direction must be MORE or LESS.")

    line = float(line)

    games = mlb_schedule_for_date(game_date)

    results = []
    errors = []

    for game in games:

        timing = game_scan_stage(
            game.get("start_time"),
            game.get("status"),
        )

        # Do not scan games that have already started.
        if timing["stage"] == "LOCKED":
            continue

        sides = [
            ("away", "home"),
            ("home", "away"),
        ]

        for team_side, opponent_side in sides:

            team = game.get(team_side) or {}
            opponent = game.get(opponent_side) or {}

            team_id = team.get("id")
            opponent_id = opponent.get("id")

            if not team_id or not opponent_id:
                continue

            try:
                roster = mlb_team_roster(int(team_id))
            except Exception as e:
                errors.append({
                    "team": team.get("name"),
                    "error": str(e),
                })
                continue

            hitters = [
                player
                for player in roster
                if player.get("position_type") != "Pitcher"
                and player.get("name")
            ]

            for player in hitters:

                player_name = player["name"]

                try:
                    analysis = analyze_mlb_verified(
                        player_name,
                        "hitter",
                        "hitter_fantasy_score",
                        line,
                        int(team_id),
                        int(opponent_id),
                        opponent.get("name"),
                    )

                    p_more = float(
                        analysis.get("p_more") or 0.0
                    )

                    p_less = float(
                        analysis.get("p_less") or (1.0 - p_more)
                    )

                    selected_probability = (
                        p_more
                        if direction == "MORE"
                        else p_less
                    )

                    pregame = analysis.get("pregame") or {}

                    # A scanner candidate must agree with the
                    # requested direction. PASS stays PASS.
                    qualifies = (
                        analysis.get("lean") == direction
                        and analysis.get("confidence") in (
                            "MODERATE",
                            "HIGH",
                        )
                    )

                    # FINAL PICK requires:
                    # 1. model qualifies
                    # 2. game is in FINAL CHECK
                    # 3. hitter is confirmed in starting lineup
                    final_pick = (
                        qualifies
                        and timing["stage"] == "FINAL CHECK"
                        and pregame.get("in_starting_lineup") is True
                    )

                    results.append({
                        "player": player_name,
                        "player_id": player.get("id"),
                        "team": team.get("name"),
                        "team_id": team_id,
                        "opponent": opponent.get("name"),
                        "opponent_id": opponent_id,
                        "game_id": game.get("game_id"),
                        "game_status": game.get("status"),
                        "start_time": game.get("start_time"),
                        "scan_stage": timing["stage"],
                        "minutes_to_game": timing["minutes_to_game"],
                        "prop": "hitter_fantasy_score",
                        "line": line,
                        "direction": direction,
                        "projection": analysis.get("projection"),
                        "p_more": p_more,
                        "p_less": p_less,
                        "selected_probability": selected_probability,
                        "lean": analysis.get("lean"),
                        "confidence": analysis.get("confidence"),
                        "qualifies": qualifies,
                        "final_pick": final_pick,
                        "in_starting_lineup": pregame.get(
                            "in_starting_lineup"
                        ),
                        "batting_order": pregame.get(
                            "batting_order"
                        ),
                        "lineup_warning": analysis.get(
                            "lineup_warning"
                        ),
                    })

                except Exception as e:
                    errors.append({
                        "player": player_name,
                        "team": team.get("name"),
                        "opponent": opponent.get("name"),
                        "error": str(e),
                    })

    # Requested direction determines ranking.
    results.sort(
        key=lambda item: item["selected_probability"],
        reverse=True,
    )

    scan_output = {
        "date": game_date,
        "prop": "hitter_fantasy_score",
        "line": line,
        "direction": direction,
        "games_found": len(games),
        "players_analyzed": len(results),
        "qualifying_count": sum(
            1 for item in results
            if item["qualifies"]
        ),
        "final_pick_count": sum(
            1 for item in results
            if item["final_pick"]
        ),
        "results": results,
        "errors": errors,
    }

    # Scanner is finished. Clear temporary responses so the
    # normal MLB analyzer always starts with fresh API data.
    set_mlb_api_cache(False)

    return scan_output



# ============================================================
# PRIZEPICKS MLB MULTI-PROP SCANNER
# ============================================================

MLB_PP_HITTER_PROPS = {
    "hits",
    "total_bases",
    "runs",
    "rbi",
    "walks",
    "home_runs",
    "hitter_fantasy_score",
}

MLB_PP_PITCHER_PROPS = {
    "strikeouts",
    "pitching_outs",
    "hits_allowed",
    "walks_allowed",
    "earned_runs",
    "pitcher_fantasy_score",
}


def scan_mlb_prizepicks(prop_filter=None):
    """
    Scan current standard PrizePicks MLB props.

    PrizePicks supplies:
        player
        prop
        current standard line

    Our MLB model independently supplies:
        projection
        P(MORE)
        P(LESS)
        MORE / LESS / PASS

    prop_filter:
        None / "ALL" = all supported MLB props
        otherwise PrizePicks display prop such as
        "Hits", "Total Bases", "Pitcher Strikeouts", etc.
    """

    board = get_prizepicks_board()

    pp_rows = get_supported_board(
        "MLB",
        board=board,
    )

    prop_filter = str(
        prop_filter or "ALL"
    ).strip()

    if prop_filter.upper() != "ALL":
        pp_rows = [
            row for row in pp_rows
            if row.get("prop") == prop_filter
        ]

    results = []
    errors = []

    # --------------------------------------------------------
    # Independent market consensus
    # --------------------------------------------------------
    #
    # Enrich the PrizePicks board ONCE before running the
    # individual player models.
    #
    # The bridge groups props by game and makes at most one
    # multi-market PropLine odds request per matched game.
    #
    # Rows without sufficient independent market information
    # will fall back to the existing PP Market Guard V1.
    market_rows_by_projection = {}
    market_bridge_summary = {
        "available": False,
        "games": 0,
        "matched_games": 0,
        "market_requests": 0,
        "market_rows": 0,
        "errors": [],
    }

    try:
        market_bridge = (
            enrich_mlb_pp_board_with_market(
                pp_rows,
                force_refresh=False,
            )
        )

        for market_row in market_bridge.get(
            "rows",
            [],
        ):
            projection_id = market_row.get(
                "projection_id"
            )

            if projection_id is not None:
                market_rows_by_projection[
                    str(projection_id)
                ] = market_row

        market_bridge_summary = {
            "available": True,
            "games": market_bridge.get(
                "games",
                0,
            ),
            "matched_games": market_bridge.get(
                "matched_games",
                0,
            ),
            "market_requests": market_bridge.get(
                "market_requests",
                0,
            ),
            "market_rows": len(
                market_bridge.get(
                    "rows",
                    [],
                )
            ),
            "errors": market_bridge.get(
                "errors",
                [],
            ),
        }

    except Exception as exc:
        # Market data must never crash the MLB model scanner.
        # Existing Market Guard V1 remains available.
        market_bridge_summary = {
            "available": False,
            "games": 0,
            "matched_games": 0,
            "market_requests": 0,
            "market_rows": 0,
            "errors": [
                {
                    "status":
                        "MARKET_BRIDGE_ERROR",
                    "error": str(exc),
                }
            ],
        }

    clear_mlb_api_cache()
    set_mlb_api_cache(True)

    try:
        # PrizePicks can contain games from more than one
        # calendar date. Build schedule/roster lookups for every
        # date represented on the current PP board.
        from datetime import datetime

        pp_dates = set()

        for pp_row in pp_rows:
            start_time = pp_row.get("start_time")

            if not start_time:
                continue

            try:
                dt = datetime.fromisoformat(
                    start_time.replace("Z", "+00:00")
                )

                # PrizePicks timestamps are UTC.
                # Convert to Eastern before choosing the MLB
                # calendar date. This prevents late games such
                # as 9:40 PM ET from being treated as tomorrow
                # because they are after midnight UTC.
                eastern_dt = dt.astimezone(
                    ZoneInfo("America/New_York")
                )

                pp_dates.add(
                    eastern_dt.date().isoformat()
                )
            except Exception:
                continue

        player_lookup = {}

        for pp_date in sorted(pp_dates):

            games = mlb_schedule_for_date(pp_date)

            for game in games:

                timing = game_scan_stage(
                    game.get("start_time"),
                    game.get("status"),
                )

                if timing["stage"] == "LOCKED":
                    continue

                for team_side, opponent_side in (
                    ("away", "home"),
                    ("home", "away"),
                ):

                    team = game.get(team_side) or {}
                    opponent = game.get(opponent_side) or {}

                    team_id = team.get("id")
                    opponent_id = opponent.get("id")

                    if not team_id or not opponent_id:
                        continue

                    try:
                        roster = mlb_team_roster(
                            int(team_id)
                        )
                    except Exception as exc:
                        errors.append({
                            "team": team.get("name"),
                            "date": pp_date,
                            "status": "ROSTER_ERROR",
                            "error": str(exc),
                        })
                        continue

                    for player in roster:

                        name = player.get("name")

                        if not name:
                            continue

                        # Keep both exact and normalized roster keys.
                        # This fixes accents/punctuation without dangerous
                        # fuzzy matching.
                        normalized_name = normalize_mlb_player_name(name)

                        player_record = {
                            "player_id": player.get("id"),
                            "position_type": player.get(
                                "position_type"
                            ),
                            "team": team.get("name"),
                            "team_id": int(team_id),
                            "opponent": opponent.get("name"),
                            "opponent_id": int(opponent_id),
                            "game_id": game.get("game_id"),
                            "game_status": game.get("status"),
                            "start_time": game.get("start_time"),
                            "game_date": pp_date,
                            "timing": timing,
                        }

                        player_lookup[name] = player_record

                        if normalized_name:
                            player_lookup[normalized_name] = player_record

        # ----------------------------------------------------
        # MLB SCANNER PERFORMANCE CACHE
        # ----------------------------------------------------
        # PrizePicks can contain hundreds of rows. Some rows can
        # resolve to the same player/prop/line/game analysis.
        #
        # Never cache only by player: different props and lines
        # require different model calculations.
        analysis_cache = {}
        analysis_cache_hits = 0
        analysis_cache_misses = 0

        for pp in pp_rows:

            player_name = pp.get("player")
            pp_prop = pp.get("prop")
            model_prop = pp.get("model_prop")

            try:
                line = float(pp.get("line"))
            except (TypeError, ValueError):
                errors.append({
                    "player": player_name,
                    "prop": pp_prop,
                    "status": "INVALID_LINE",
                })
                continue

            player_info = player_lookup.get(
                player_name
            )

            # Safe fallback for accents/punctuation/name formatting.
            if not player_info:
                player_info = player_lookup.get(
                    normalize_mlb_player_name(player_name)
                )

            if not player_info:
                errors.append({
                    "player": player_name,
                    "prop": pp_prop,
                    "line": line,
                    "status": "PLAYER_NOT_MATCHED",
                })
                continue

            if model_prop in MLB_PP_HITTER_PROPS:
                player_type = "hitter"

            elif model_prop in MLB_PP_PITCHER_PROPS:
                player_type = "pitcher"

            else:
                errors.append({
                    "player": player_name,
                    "prop": pp_prop,
                    "line": line,
                    "status": "UNSUPPORTED_MODEL_PROP",
                })
                continue

            try:
                # Exact model-input cache. This changes NO model math.
                # We only reuse a result when every model-defining input
                # is identical.
                analysis_key = (
                    normalize_mlb_player_name(player_name),
                    player_type,
                    model_prop,
                    float(line),
                    int(player_info["team_id"]),
                    int(player_info["opponent_id"]),
                    str(player_info["opponent"]),
                )

                if analysis_key in analysis_cache:
                    analysis = analysis_cache[analysis_key]
                    analysis_cache_hits += 1
                else:
                    analysis = analyze_mlb_verified(
                        player_name,
                        player_type,
                        model_prop,
                        line,
                        player_info["team_id"],
                        player_info["opponent_id"],
                        player_info["opponent"],
                    )

                    analysis_cache[analysis_key] = analysis
                    analysis_cache_misses += 1

                p_more = float(
                    analysis.get("p_more") or 0.0
                )

                p_less = float(
                    analysis.get("p_less")
                    if analysis.get("p_less") is not None
                    else (1.0 - p_more)
                )

                lean = analysis.get("lean")
                confidence = analysis.get(
                    "confidence"
                )

                pregame = (
                    analysis.get("pregame") or {}
                )

                strongest_probability = max(
                    p_more,
                    p_less,
                )

                # -----------------------------------------
                # PrizePicks market sanity guard
                # -----------------------------------------
                #
                # The model projection remains independent.
                # PrizePicks supplies the market line only.
                #
                # A very strong disagreement with the market
                # is NOT automatically treated as a stronger
                # play. Extreme model probabilities receive
                # additional scrutiny.
                #
                # V1 intentionally uses probability rather
                # than raw percentage projection difference,
                # because a 0.5 Hits line behaves very
                # differently from a 5.5 strikeout line.

                raw_confidence = confidence
                raw_lean = lean

                projection_value = analysis.get(
                    "projection"
                )

                try:
                    projection_value = float(
                        projection_value
                    )
                except (TypeError, ValueError):
                    projection_value = None

                model_edge = (
                    projection_value - line
                    if projection_value is not None
                    else None
                )

                market_status = "NORMAL"
                market_warning = None

                # 70%+ against a standard PP line is a
                # substantial model/market disagreement.
                # Do not allow it to remain an automatic
                # HIGH-confidence candidate without further
                # validation.
                if (
                    lean in ("MORE", "LESS")
                    and strongest_probability >= 0.70
                ):
                    market_status = "REVIEW"

                    market_warning = (
                        "Large model/PrizePicks disagreement; "
                        "requires additional pregame validation."
                    )

                    if confidence == "HIGH":
                        confidence = "MODERATE"

                # 75%+ is treated as extreme disagreement.
                # Until residual calibration proves the model
                # can reliably exploit gaps this large, PASS.
                if (
                    lean in ("MORE", "LESS")
                    and strongest_probability >= 0.75
                ):
                    market_status = "EXTREME"

                    market_warning = (
                        "Extreme model/PrizePicks disagreement; "
                        "market guard forced PASS."
                    )

                    lean = "PASS"
                    confidence = "PASS"

                # -----------------------------------------
                # Independent PropLine market check
                # -----------------------------------------
                #
                # PrizePicks remains the TARGET line.
                #
                # PropLine provides an independent exact-line
                # market reference when enough books exist.
                #
                # If the market is unavailable/insufficient,
                # the V1 guard above remains the fallback.

                market_row = (
                    market_rows_by_projection.get(
                        str(
                            pp.get(
                                "projection_id"
                            )
                        )
                    )
                )

                independent_market_available = False
                independent_market_reason = None
                independent_market_lean = None
                independent_market_probability = None
                independent_market_strength = (
                    "UNAVAILABLE"
                )
                independent_market_books = 0
                independent_market_dispersion = None
                independent_market_outliers_removed = 0

                market_check = "FALLBACK_V1"
                market_agreement = None
                market_recommended_action = (
                    "FALLBACK"
                )

                if market_row:
                    independent_market_available = (
                        bool(
                            market_row.get(
                                "market_available"
                            )
                        )
                    )

                    independent_market_reason = (
                        market_row.get(
                            "market_reason"
                        )
                    )

                    independent_market_lean = (
                        market_row.get(
                            "market_lean"
                        )
                    )

                    independent_market_probability = (
                        market_row.get(
                            "market_probability"
                        )
                    )

                    independent_market_strength = (
                        market_row.get(
                            "market_strength",
                            "UNAVAILABLE",
                        )
                    )

                    independent_market_books = (
                        market_row.get(
                            "market_books",
                            0,
                        )
                    )

                    independent_market_dispersion = (
                        market_row.get(
                            "market_dispersion"
                        )
                    )

                    independent_market_outliers_removed = (
                        market_row.get(
                            "market_outliers_removed",
                            0,
                        )
                    )

                    market_result = {
                        "available":
                            independent_market_available,

                        "market_lean":
                            independent_market_lean,

                        "market_probability":
                            independent_market_probability,

                        "market_strength":
                            independent_market_strength,
                    }

                    comparison = (
                        compare_model_to_market(
                            model_lean=raw_lean,
                            model_probability=
                                strongest_probability,
                            market_result=
                                market_result,
                        )
                    )

                    market_check = comparison.get(
                        "market_check",
                        "FALLBACK_V1",
                    )

                    market_agreement = (
                        comparison.get(
                            "market_agreement"
                        )
                    )

                    market_recommended_action = (
                        comparison.get(
                            "recommended_action",
                            "FALLBACK",
                        )
                    )

                    # Meaningful independent market
                    # disagreement can force PASS.
                    if (
                        market_recommended_action
                        == "PASS"
                    ):
                        lean = "PASS"
                        confidence = "PASS"

                        market_status = (
                            "INDEPENDENT_MARKET_PASS"
                        )

                        market_warning = (
                            "Independent exact-line market "
                            "meaningfully disagrees with "
                            "the model; forced PASS."
                        )

                    # When independent market evidence is
                    # usable and does not reject the model,
                    # restore the original model decision.
                    #
                    # This prevents the temporary V1
                    # probability guard from overriding a
                    # model opinion that has passed the
                    # stronger independent market check.
                    elif (
                        market_recommended_action
                        in ("MORE", "LESS")
                    ):
                        lean = raw_lean
                        confidence = raw_confidence

                        market_status = (
                            "INDEPENDENT_MARKET_CHECKED"
                        )

                        if (
                            market_agreement is True
                        ):
                            market_warning = (
                                "Model direction agrees "
                                "with independent exact-line "
                                "market consensus."
                            )
                        elif (
                            independent_market_lean
                            == "NEUTRAL"
                        ):
                            market_warning = (
                                "Independent market is "
                                "neutral; model direction "
                                "retained."
                            )
                        else:
                            market_warning = (
                                "Independent market evidence "
                                "is weak; model direction "
                                "retained."
                            )

                    # FALLBACK means the existing V1 result
                    # remains untouched.

                qualifies = (
                    lean in ("MORE", "LESS")
                    and confidence in (
                        "MODERATE",
                        "HIGH",
                    )
                )

                timing = player_info["timing"]

                # Hitters require confirmed lineup for
                # FINAL PICK status.
                if player_type == "hitter":
                    lineup_ready = (
                        pregame.get(
                            "in_starting_lineup"
                        ) is True
                    )
                else:
                    # Pitchers are handled by the verified
                    # pregame/model checks.
                    lineup_ready = True

                final_pick = (
                    qualifies
                    and timing["stage"]
                    == "FINAL CHECK"
                    and lineup_ready
                )

                market_verified = (
                    independent_market_available
                    and independent_market_books >= 3
                    and independent_market_strength != "INSUFFICIENT"
                    and market_recommended_action in ("MORE", "LESS")
                )
                if not qualifies:
                    readiness = "PASS"
                elif final_pick and market_verified:
                    readiness = "VERIFIED"
                else:
                    readiness = "STRONG — PREGAME PENDING"

                results.append({
                    "sport": "MLB",
                    "readiness": readiness,
                    "sport": "MLB",
                    "readiness": readiness,
                    "projection_id": pp.get(
                        "projection_id"
                    ),
                    "player": player_name,
                    "player_id": player_info.get(
                        "player_id"
                    ),
                    "player_type": player_type,

                    "team": player_info["team"],
                    "team_id": player_info["team_id"],
                    "opponent": player_info[
                        "opponent"
                    ],
                    "opponent_id": player_info[
                        "opponent_id"
                    ],

                    "game_id": player_info["game_id"],
                    "game_status": player_info[
                        "game_status"
                    ],
                    "start_time": player_info[
                        "start_time"
                    ],

                    "scan_stage": timing["stage"],
                    "minutes_to_game": timing[
                        "minutes_to_game"
                    ],

                    "pp_prop": pp_prop,
                    "model_prop": model_prop,
                    "pp_line": line,
                    "odds_type": pp.get(
                        "odds_type"
                    ),
                    "pp_updated_at": pp.get(
                        "updated_at"
                    ),

                    "projection": analysis.get(
                        "projection"
                    ),

                    "p_more": p_more,
                    "p_less": p_less,

                    "lean": lean,
                    "confidence": confidence,

                    "raw_lean": raw_lean,
                    "raw_confidence": raw_confidence,

                    "model_edge": model_edge,

                    # Final market decision metadata.
                    "market_status": market_status,
                    "market_warning": market_warning,

                    # Independent PropLine market metadata.
                    "independent_market_available":
                        independent_market_available,

                    "independent_market_reason":
                        independent_market_reason,

                    "independent_market_lean":
                        independent_market_lean,

                    "independent_market_probability":
                        independent_market_probability,

                    "independent_market_strength":
                        independent_market_strength,

                    "independent_market_books":
                        independent_market_books,

                    "independent_market_dispersion":
                        independent_market_dispersion,

                    "independent_market_outliers_removed":
                        independent_market_outliers_removed,

                    "market_check": market_check,
                    "market_agreement":
                        market_agreement,

                    "market_recommended_action":
                        market_recommended_action,

                    "strongest_probability":
                        strongest_probability,

                    "qualifies": qualifies,
                    "final_pick": final_pick,

                    "in_starting_lineup":
                        pregame.get(
                            "in_starting_lineup"
                        ),

                    "batting_order":
                        pregame.get(
                            "batting_order"
                        ),

                    "lineup_warning":
                        analysis.get(
                            "lineup_warning"
                        ),

                    "status": (
                        "FINAL PICK"
                        if final_pick
                        else (
                            "CANDIDATE"
                            if qualifies
                            else "PASS"
                        )
                    ),
                })

            except Exception as exc:

                # Insufficient history or another model
                # limitation should not crash the scan.
                errors.append({
                    "player": player_name,
                    "prop": pp_prop,
                    "line": line,
                    "status": "MODEL_PASS",
                    "error": str(exc),
                })

        # Strongest supported model opinions first.
        results.sort(
            key=lambda item: item[
                "strongest_probability"
            ],
            reverse=True,
        )

        return {
            "sport": "MLB",
            "source": "PrizePicks",
            "board_type": "standard",
            "prop_filter": prop_filter,
            "board_props_found": len(pp_rows),
            "players_analyzed": len(results),

            "performance": {
                "analysis_cache_hits": analysis_cache_hits,
                "analysis_cache_misses": analysis_cache_misses,
                "unique_model_analyses": len(analysis_cache),
            },
            "qualifying_count": sum(
                1 for item in results
                if item["qualifies"]
            ),
            "final_pick_count": sum(
                1 for item in results
                if item["final_pick"]
            ),

            "market_bridge":
                market_bridge_summary,

            "market_checked_count": sum(
                1 for item in results
                if item.get(
                    "independent_market_available"
                )
            ),

            "market_pass_count": sum(
                1 for item in results
                if item.get(
                    "market_check"
                ) in (
                    "STRONG_MARKET_DISAGREEMENT",
                    "MARKET_DISAGREEMENT",
                )
            ),

            "results": results,
            "errors": errors,
        }

    finally:
        # Always restore normal MLB API behavior,
        # including when an exception occurs.
        set_mlb_api_cache(False)




# ============================================================
# WNBA AUTOMATIC PRIZEPICKS SCANNER
# ============================================================

def _wnba_team_norm(value):
    return str(value or "").strip().upper().replace(" ", "")


def _wnba_opponent_from_pp(player_team, pp):
    aliases = {
        "CONNECTICUTSUN":"CON", "CT":"CON", "CON":"CON",
        "ATLANTADREAM":"ATL", "ATL":"ATL", "CHICAGOSKY":"CHI", "CHI":"CHI",
        "DALLASWINGS":"DAL", "DAL":"DAL", "GOLDENSTATEVALKYRIES":"GS", "GSV":"GS", "GS":"GS",
        "INDIANAFEVER":"IND", "IND":"IND", "LOSANGELESSPARKS":"LA", "LASPARKS":"LA", "LA":"LA",
        "LASVEGASACES":"LV", "LAS":"LV", "LV":"LV", "MINNESOTALYNX":"MIN", "MIN":"MIN",
        "NEWYORKLIBERTY":"NY", "NYL":"NY", "NY":"NY", "PHOENIXMERCURY":"PHX", "PHX":"PHX",
        "SEATTLESTORM":"SEA", "SEA":"SEA", "WASHINGTONMYSTICS":"WAS", "WSH":"WAS", "WAS":"WAS",
        "PORTLANDFIRE":"POR", "POR":"POR", "TORONTOTEMPO":"TOR", "TOR":"TOR",
    }
    def canon(x):
        k=_wnba_team_norm(x); return aliases.get(k,k)
    team=canon(player_team); away=canon(pp.get("away_team") or pp.get("away")); home=canon(pp.get("home_team") or pp.get("home"))
    if team and team == away: return home
    if team and team == home: return away
    return None


def scan_wnba_prizepicks(prop_filter=None):
    board=get_prizepicks_board()
    rows=get_supported_board("WNBA", board=board)
    supported=set(WNBA_MARKET_MAP) | {"minutes"}
    rows=[r for r in rows if (r.get("model_prop") or r.get("prop")) in supported]
    prop_filter=str(prop_filter or "ALL").strip()
    if prop_filter.upper() != "ALL": rows=[r for r in rows if r.get("prop") == prop_filter]

    market_by_projection={}; market_summary={"available":False,"games":0,"matched_games":0,"market_requests":0,"market_rows":0,"errors":[]}
    try:
        bridge=enrich_wnba_pp_board_with_market(rows, force_refresh=False)
        for mr in bridge.get("rows",[]):
            if mr.get("projection_id") is not None: market_by_projection[str(mr.get("projection_id"))]=mr
        market_summary={"available":True,"games":bridge.get("games",0),"matched_games":bridge.get("matched_games",0),"market_requests":bridge.get("market_requests",0),"market_rows":len(bridge.get("rows",[])),"errors":bridge.get("errors",[]),"usage":bridge.get("usage",{})}
    except Exception as exc:
        market_summary["errors"]=[{"status":"MARKET_BRIDGE_ERROR","error":str(exc)}]

    injury_available=False; injuries=[]
    try:
        raw=get_wnba_injuries(); injuries=parse_injuries(raw) if raw else []; injury_available=raw is not None
    except Exception:
        injuries=[]

    injury_lookup={str(x.get("player") or "").strip().lower():x for x in injuries}
    results=[]; errors=[]
    for pp in rows:
        player=pp.get("player"); model_prop=pp.get("model_prop") or pp.get("prop")
        try: line=float(pp.get("line"))
        except (TypeError,ValueError):
            errors.append({"player":player,"status":"INVALID_LINE"}); continue
        try:
            games=get_player_games(player, season=CURRENT_SEASON)
            if not games: raise ValueError("No current-season WNBA games in database")

            # get_player_games() returns sqlite3.Row objects.
            # Convert them to normal dictionaries so scanner/model
            # code can safely use .get().
            games=[
                dict(game) if not isinstance(game, dict) else game
                for game in games
            ]

            latest=sorted(
                games,
                key=lambda g:str(g.get("date") or "")
            )[-1]

            team=latest.get("team")
            opponent=_wnba_opponent_from_pp(team,pp)

            pred=predict_prop_v1(
                games,
                model_prop,
                line,
                opponent,
                None
            )
            if not pred: raise ValueError("WNBA V2 returned no prediction")
            p_more=float(pred.get("p_more") or 0); p_less=float(pred.get("p_less") if pred.get("p_less") is not None else 1-p_more)
            raw_lean=str(pred.get("lean") or "PASS").upper(); raw_conf=str(pred.get("confidence") or "LOW").upper()
            lean=raw_lean; confidence=raw_conf; strongest=max(p_more,p_less)
            projection=float(pred.get("projection")); edge=projection-line
            role_unstable=bool(pred.get("role_unstable")); minutes_context=pred.get("minutes_context") or {}
            timing=game_scan_stage(pp.get("start_time") or pp.get("game_start_time"), pp.get("game_status"))

            # --------------------------------------------------------
            # WNBA availability / injury / role verification
            # --------------------------------------------------------
            injury=injury_lookup.get(str(player or "").strip().lower())
            injury_status=str((injury or {}).get("status") or "").upper().strip()

            blocking=any(
                x in injury_status
                for x in ("OUT","DOUBTFUL","INACTIVE")
            )

            uncertain=any(
                x in injury_status
                for x in (
                    "QUESTIONABLE",
                    "GAME TIME",
                    "GAME-TIME",
                    "GTD",
                )
            )

            positive_status=any(
                x in injury_status
                for x in (
                    "ACTIVE",
                    "AVAILABLE",
                    "PROBABLE",
                )
            )

            # Important:
            # Not being listed on the injury report is NOT proof that
            # the player is active. It simply means we found no
            # negative injury flag.
            no_negative_injury_flag=(
                injury_available
                and not blocking
                and not uncertain
            )

            availability_confirmed=(
                injury_available
                and bool(injury)
                and positive_status
                and not blocking
                and not uncertain
            )

            if blocking:
                lean="PASS"
                confidence="PASS"

            mr=market_by_projection.get(
                str(pp.get("projection_id"))
            )

            market_available=bool(
                (mr or {}).get("market_available")
            )
            market_strength=(
                (mr or {}).get(
                    "market_strength",
                    "UNAVAILABLE"
                )
            )
            market_books=int(
                (mr or {}).get("market_books") or 0
            )
            market_lean=(mr or {}).get("market_lean")
            market_prob=(mr or {}).get(
                "market_probability"
            )
            market_disp=(mr or {}).get(
                "market_dispersion"
            )

            market_result={
                "available":market_available,
                "market_lean":market_lean,
                "market_probability":market_prob,
                "market_strength":market_strength,
            }

            comparison=compare_model_to_market(
                raw_lean,
                strongest,
                market_result,
            )

            action=comparison.get(
                "recommended_action",
                "FALLBACK",
            )

            if action=="PASS":
                lean="PASS"
                confidence="PASS"
            elif action in ("MORE","LESS") and lean!="PASS":
                lean=action

            qualifies=(
                lean in ("MORE","LESS")
                and confidence in ("MODERATE","HIGH")
                and not blocking
            )

            market_verified=(
                market_available
                and market_books >= 3
                and market_strength
                    not in ("INSUFFICIENT","UNAVAILABLE")
                and action in ("MORE","LESS")
            )

            # Model already calculates role_unstable using the
            # player's recent minutes/opportunity profile.
            role_ready=not role_unstable

            final_window=(
                timing.get("stage")=="FINAL CHECK"
            )

            # A questionable/GTD player can never be VERIFIED.
            #
            # A player absent from the injury report is NOT called
            # confirmed active. But if the report itself is available,
            # there is no negative flag, the role is stable, and we are
            # in FINAL CHECK, the pregame check may clear.
            pregame_ready = (
            final_window
            and availability_confirmed
            and role_ready
        )

            verified=(
                qualifies
                and market_verified
                and pregame_ready
            )

            if not qualifies:
                readiness="PASS"
            elif verified:
                readiness="VERIFIED"
            else:
                readiness="STRONG — PREGAME PENDING"

            results.append({
                "sport":"WNBA","projection_id":pp.get("projection_id"),"player":player,"player_id":pp.get("player_id"),"player_type":"player",
                "team":team,"opponent":opponent,"game_id":pp.get("game_id"),"game_status":pp.get("game_status"),"start_time":pp.get("start_time") or pp.get("game_start_time"),
                "scan_stage":timing.get("stage"),"minutes_to_game":timing.get("minutes_to_game"),"pp_prop":pp.get("prop"),"model_prop":model_prop,"pp_line":line,
                "projection":projection,"p_more":p_more,"p_less":p_less,"lean":lean,"confidence":confidence,"raw_lean":raw_lean,"raw_confidence":raw_conf,
                "strongest_probability":strongest,"model_edge":edge,"role_unstable":role_unstable,"minutes_context":minutes_context,
                "injury_data_available":injury_available,
                "injury_status":injury_status or ("NO CURRENT LISTING — ACTIVE NOT CONFIRMED" if injury_available else "UNAVAILABLE"),
                "injury_detail":((injury or {}).get("injury") or (injury or {}).get("detail")),
                "availability_confirmed":availability_confirmed,
                "no_negative_injury_flag":no_negative_injury_flag,
                "role_ready":role_ready,
                "pregame_ready":pregame_ready,
                "final_window":final_window,
                "independent_market_available":market_available,"independent_market_reason":(mr or {}).get("market_reason"),"independent_market_lean":market_lean,
                "independent_market_probability":market_prob,"independent_market_strength":market_strength,"independent_market_books":market_books,
                "independent_market_dispersion":market_disp,"market_check":comparison.get("market_check"),"market_agreement":comparison.get("market_agreement"),
                "market_recommended_action":action,"market_status":"NORMAL" if market_verified else "PENDING","market_warning":None if market_verified else "Independent WNBA market confirmation pending or insufficient.",
                "qualifies":qualifies,"final_pick":verified,"readiness":readiness,"status":"VERIFIED" if verified else ("CANDIDATE" if qualifies else "PASS"),
            })
        except Exception as exc:
            errors.append({"player":player,"prop":pp.get("prop"),"line":line,"status":"MODEL_PASS","error":str(exc)})
    results.sort(
        key=lambda x:x.get("strongest_probability",0),
        reverse=True
    )

    qualifying_count=sum(
        1 for x in results
        if x.get("qualifies")
    )

    verified_count=sum(
        1 for x in results
        if x.get("readiness")=="VERIFIED"
    )

    pending_count=sum(
        1 for x in results
        if x.get("readiness")=="STRONG — PREGAME PENDING"
    )

    pass_count=sum(
        1 for x in results
        if x.get("readiness")=="PASS"
    )

    market_checked_count=sum(
        1 for x in results
        if x.get("independent_market_available")
    )

    summary={
        "sport":"WNBA",
        "board_props_found":len(rows),
        "players_analyzed":len(results),
        "qualifying_count":qualifying_count,
        "verified_count":verified_count,
        "pending_count":pending_count,
        "pass_count":pass_count,
        "final_pick_count":verified_count,
        "market_checked_count":market_checked_count,
        "error_count":len(errors),
    }

    return {
        "sport":"WNBA",
        "source":"PrizePicks",
        "board_type":"standard_full_game",
        "prop_filter":prop_filter,

        # Keep old top-level API fields for compatibility.
        "board_props_found":len(rows),
        "players_analyzed":len(results),
        "qualifying_count":qualifying_count,
        "verified_count":verified_count,
        "pending_count":pending_count,
        "pass_count":pass_count,
        "final_pick_count":verified_count,
        "market_checked_count":market_checked_count,

        # New consistent summary.
        "summary":summary,

        "market_bridge":market_summary,
        "results":results,
        "errors":errors,
    }


# ============================================================
# TRACKING ROUTES
# ============================================================

@app.post("/api/tracking/save")
def api_tracking_save():

    payload = request.get_json(
        silent=True
    ) or {}

    rows = payload.get("results") or []

    if not isinstance(rows, list):
        return jsonify({
            "error": "results must be a list"
        }), 400

    saved = 0
    duplicates = 0
    skipped = 0

    con = tracking_connection()

    try:

        for row in rows:

            if not isinstance(row, dict):
                skipped += 1
                continue

            player = row.get("player")
            pp_prop = row.get("pp_prop")
            pp_line = row.get("pp_line")

            if (
                not player
                or not pp_prop
                or pp_line is None
            ):
                skipped += 1
                continue

            try:
                pp_line = float(pp_line)
            except (TypeError, ValueError):
                skipped += 1
                continue

            market_agreement = row.get(
                "market_agreement"
            )

            if market_agreement is True:
                market_agreement_db = 1
            elif market_agreement is False:
                market_agreement_db = 0
            else:
                market_agreement_db = None

            values = (
                datetime.now().astimezone().isoformat(),

                str(row.get("sport") or payload.get("sport") or "MLB").upper(),
                str(
                    row.get("projection_id")
                    or ""
                ),

                str(
                    row.get("game_id")
                    or ""
                ),

                row.get("start_time"),

                player,

                str(
                    row.get("player_id")
                    or ""
                ),

                row.get("player_type"),

                row.get("team"),
                row.get("opponent"),

                pp_prop,
                row.get("model_prop"),
                pp_line,

                row.get("projection"),

                row.get("p_more"),
                row.get("p_less"),
                row.get(
                    "strongest_probability"
                ),

                row.get("raw_lean"),
                row.get("raw_confidence"),

                row.get("lean"),
                row.get("confidence"),

                row.get("model_edge"),

                1 if row.get(
                    "independent_market_available"
                ) else 0,

                row.get(
                    "independent_market_lean"
                ),

                row.get(
                    "independent_market_probability"
                ),

                row.get(
                    "independent_market_strength"
                ),

                row.get(
                    "independent_market_books"
                ),

                row.get(
                    "independent_market_dispersion"
                ),

                row.get("market_check"),

                market_agreement_db,

                row.get("scan_stage"),
                row.get("status"),

                1 if row.get(
                    "qualifies"
                ) else 0,

                1 if row.get(
                    "final_pick"
                ) else 0,
            )

            before = con.total_changes

            con.execute(
                """
                INSERT OR IGNORE INTO predictions (
                    saved_at,
                    sport,
                    projection_id,

                    game_id,
                    game_start_time,

                    player,
                    player_id,
                    player_type,

                    team,
                    opponent,

                    pp_prop,
                    model_prop,
                    pp_line,

                    projection,

                    p_more,
                    p_less,
                    strongest_probability,

                    raw_lean,
                    raw_confidence,

                    final_lean,
                    final_confidence,

                    model_edge,

                    market_available,
                    market_lean,
                    market_probability,
                    market_strength,
                    market_books,
                    market_dispersion,
                    market_check,
                    market_agreement,

                    scan_stage,
                    scanner_status,
                    qualifies,
                    final_pick
                )
                VALUES (
                    ?,?,?,?,?,?,?,?,?,?,
                    ?,?,?,?,?,?,?,?,?,?,
                    ?,?,?,?,?,?,?,?,?,?,
                    ?,?,?,?
                )
                """,
                values,
            )

            if con.total_changes > before:
                saved += 1
            else:
                duplicates += 1

        con.commit()

    finally:
        con.close()

    return jsonify({
        "ok": True,
        "processed": len(rows),
        "saved": saved,
        "duplicates": duplicates,
        "skipped": skipped,
    })


@app.get("/api/tracking/predictions")
def api_tracking_predictions():

    con = tracking_connection()

    rows = con.execute(
        """
        SELECT *
        FROM predictions
        ORDER BY
            game_start_time DESC,
            strongest_probability DESC,
            id DESC
        """
    ).fetchall()

    con.close()

    return jsonify([
        dict(row)
        for row in rows
    ])


@app.get("/results")
def tracking_results_page():
    return render_template(
        "results.html"
    )


@app.delete("/api/tracking/predictions/<int:prediction_id>")
def api_tracking_delete_prediction(prediction_id):

    con = tracking_connection()

    try:
        before = con.total_changes

        con.execute(
            """
            DELETE FROM predictions
            WHERE id = ?
            """,
            (prediction_id,),
        )

        deleted = (
            con.total_changes - before
        )

        con.commit()

    finally:
        con.close()

    return jsonify({
        "ok": True,
        "deleted": deleted,
        "prediction_id": prediction_id,
    })


@app.delete("/api/tracking/date/<game_date>")
def api_tracking_delete_date(game_date):

    # Require YYYY-MM-DD.
    try:
        datetime.strptime(
            game_date,
            "%Y-%m-%d",
        )
    except ValueError:
        return jsonify({
            "error":
                "Date must be YYYY-MM-DD"
        }), 400

    con = tracking_connection()

    try:
        before = con.total_changes

        con.execute(
            """
            DELETE FROM predictions
            WHERE substr(
                game_start_time,
                1,
                10
            ) = ?
            """,
            (game_date,),
        )

        deleted = (
            con.total_changes - before
        )

        con.commit()

    finally:
        con.close()

    return jsonify({
        "ok": True,
        "date": game_date,
        "deleted": deleted,
    })



# ----------------------------
# API routes
# ----------------------------

@app.get("/api/teams")
def api_teams():
    sport = request.args.get("sport", "WNBA").upper()
    game_date = request.args.get("date", "").strip()

    try:
        if sport == "MLB":
            if not game_date:
                return jsonify(mlb_teams())

            games = mlb_schedule_for_date(game_date)
            teams = {}

            for g in games:
                for side in ("away", "home"):
                    t = g[side]

                    if t.get("id"):
                        teams[str(t["id"])] = {
                            "id": t["id"],
                            "name": t.get("name") or str(t["id"]),
                            "abbreviation": t.get("abbreviation") or "",
                        }

            return jsonify(sorted(teams.values(), key=lambda x: x["name"]))

        if not game_date:
            return jsonify(wnba_teams())

        games = espn_wnba_schedule(game_date)
        teams = {}

        for g in games:
            for side in ("away", "home"):
                t = g[side]
                abbr = t.get("abbreviation")

                if abbr:
                    teams[abbr] = {
                        "id": abbr,
                        "name": t.get("name") or abbr,
                        "abbreviation": abbr,
                    }

        return jsonify(sorted(teams.values(), key=lambda x: x["name"]))

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/players")
def api_players():
    sport = request.args.get("sport", "WNBA").upper()
    team = request.args.get("team", "")

    if not team:
        return jsonify([])

    try:
        if sport == "MLB":
            return jsonify(mlb_team_roster(int(team)))

        return jsonify(wnba_roster(team))

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/wnba-opponent")
def api_wnba_opponent():
    game_date = request.args.get("date", "").strip()
    selected_team = request.args.get("team", "").strip().upper()

    if not game_date or not selected_team:
        return jsonify({"found": False, "opponent": None})

    try:
        for g in espn_wnba_schedule(game_date):
            home = g["home"]
            away = g["away"]

            home_abbr = str(home.get("abbreviation") or "").upper()
            away_abbr = str(away.get("abbreviation") or "").upper()

            if selected_team == home_abbr:
                return jsonify({
                    "found": True,
                    "game_id": g["game_id"],
                    "team": home,
                    "opponent": away,
                    "home_away": "HOME",
                    "status": g["status"],
                })

            if selected_team == away_abbr:
                return jsonify({
                    "found": True,
                    "game_id": g["game_id"],
                    "team": away,
                    "opponent": home,
                    "home_away": "AWAY",
                    "status": g["status"],
                })

        return jsonify({
            "found": False,
            "opponent": None,
            "message": "No WNBA matchup found for that team on this date.",
        })

    except Exception as e:
        return jsonify({"found": False, "error": str(e)}), 500


@app.get("/api/mlb-matchup")
def api_mlb_matchup():
    game_date = request.args.get("date", "").strip()
    team = request.args.get("team", "").strip()

    if not game_date or not team:
        return jsonify({
            "found": False,
            "message": "Select a date and team.",
            "team_probable": None,
            "opponent_probable": None,
        })

    try:
        return jsonify(mlb_matchup_for_team(game_date, team))
    except Exception as e:
        return jsonify({
            "found": False,
            "message": str(e),
            "team_probable": None,
            "opponent_probable": None,
        }), 500


@app.get("/api/wnba-history")
def api_wnba_history():
    player = request.args.get("player", "").strip()
    prop = request.args.get("prop", "points").strip().lower()
    opponent = request.args.get("opponent", "").strip().upper()

    if not player:
        return jsonify({
            "last7": [],
            "matchup_games": [],
            "matchup_average": None,
            "matchup_available": False,
        })

    try:
        games = get_player_games(player, season=CURRENT_SEASON)
        return jsonify(build_wnba_history(games, prop, opponent or None))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ----------------------------
# Main page
# ----------------------------

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    context = None

    form = {
        "sport": "WNBA",
        "player_type": "hitter",
        "date": date.today().isoformat(),
        "team": "",
        "player": "",
        "prop": "points",
        "line": "",
        "opponent": "",
        "spread": "",
    }

    if request.method == "POST":
        for k in form:
            form[k] = request.form.get(k, form[k]).strip()

        try:
            line = float(form["line"])
            sport = form["sport"].upper()

            if sport == "WNBA":
                opponent = form["opponent"].upper() or None
                spread = float(form["spread"]) if form["spread"] else None

                games = get_player_games(form["player"], season=CURRENT_SEASON)

                if not games:
                    raise ValueError("Player not found in the 2026 WNBA database.")

                pred = predict_prop_v1(
                    games,
                    form["prop"],
                    line,
                    opponent,
                    spread,
                )

                if pred is None:
                    raise ValueError("Not enough WNBA games for a prediction.")

                history = build_wnba_history(
                    games,
                    form["prop"],
                    opponent,
                )

                result = pred

                result.update({
                    "sport": "WNBA",
                    "player": games[0]["player"],
                    "prop": form["prop"].upper(),
                    "line": line,
                    "opponent": opponent,
                    **history,
                })

            else:
                if not form["team"]:
                    raise ValueError("Select an MLB team.")

                # Re-resolve the game on the server so opponent and probable
                # pitcher are never trusted only from the browser.
                matchup = mlb_matchup_for_team(form["date"], form["team"])

                if not matchup.get("found"):
                    raise ValueError(
                        matchup.get("message")
                        or "No MLB matchup found for this team and date."
                    )

                opponent_id = matchup["opponent"]["id"]
                opponent_name = matchup["opponent"]["name"]

                # Pitcher mode must use the posted probable starter.
                if form["player_type"] == "pitcher":
                    probable = matchup.get("team_probable")

                    if not probable:
                        raise ValueError(
                            "Probable starting pitcher has not been announced yet."
                        )

                    form["player"] = probable

                result = analyze_mlb_verified(
                    form["player"],
                    form["player_type"],
                    form["prop"],
                    line,
                    int(form["team"]),
                    int(opponent_id),
                    opponent_name,
                )

                result["sport"] = "MLB"

                context = mlb_pregame_game_context(
                    int(form["team"]),
                    int(opponent_id),
                )

                form["opponent"] = str(opponent_id)

        except Exception as e:
            error = str(e)

    return render_template(
        "index.html",
        form=form,
        result=result,
        error=error,
        context=context,
        current_season=CURRENT_SEASON,
        wnba_props=WNBA_PROPS,
        hitter_props=HITTER_PROPS,
        pitcher_props=PITCHER_PROPS,
    )



@app.route("/api/wnba/prizepicks-scanner", methods=["GET"])
def api_wnba_prizepicks_scanner():
    try:
        scan = scan_wnba_prizepicks(
            request.args.get("prop", "ALL")
        )

        scan = save_latest_scanner_snapshot(
            "WNBA",
            scan,
        )

        scan["snapshot_restored"] = False
        scan["snapshot_stale"] = False

        return jsonify(scan)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/mlb/prizepicks-scanner", methods=["GET"])
def api_mlb_prizepicks_scanner():
    try:
        prop = request.args.get(
            "prop",
            "ALL"
        )

        scan = scan_mlb_prizepicks(
            prop_filter=prop,
        )

        scan = save_latest_scanner_snapshot(
            "MLB",
            scan,
        )

        scan["snapshot_restored"] = False
        scan["snapshot_stale"] = False

        return jsonify(scan)

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500



@app.get("/api/scanner/latest")
def api_latest_scanner_snapshots():
    output = {}

    for sport in ("MLB", "WNBA"):
        scan = load_latest_scanner_snapshot(
            sport
        )

        if scan is not None:
            output[sport] = scan

    return jsonify({
        "ok": True,
        "sports": output,
    })


@app.get("/api/scanner/latest/<sport>")
def api_latest_scanner_snapshot(sport):
    sport = str(
        sport or ""
    ).upper()

    if sport not in {"MLB", "WNBA"}:
        return jsonify({
            "error": "Unsupported sport"
        }), 400

    scan = load_latest_scanner_snapshot(
        sport
    )

    if scan is None:
        return jsonify({
            "found": False,
            "sport": sport,
        })

    return jsonify({
        "found": True,
        "sport": sport,
        "scan": scan,
    })


@app.route("/api/mlb/scanner", methods=["GET"])
def api_mlb_scanner():
    """
    Scan today's MLB Hitter Fantasy Score board.

    Query parameters:
      date=YYYY-MM-DD
      line=4.5
      direction=MORE or LESS
    """
    try:
        game_date = request.args.get("date")
        line = float(request.args.get("line", 4.5))
        direction = request.args.get("direction", "MORE").upper()

        if not game_date:
            from datetime import date
            game_date = date.today().isoformat()

        if direction not in ("MORE", "LESS"):
            return jsonify({
                "error": "Direction must be MORE or LESS."
            }), 400

        scan = scan_mlb_hitter_fantasy_score(
            game_date,
            line=line,
            direction=direction,
        )

        return jsonify(scan)

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


if __name__ == "__main__":
    app.run(debug=True)
