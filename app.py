from flask import Flask, render_template, request, jsonify
import sqlite3
from datetime import date, datetime
import requests

from main import get_player_games, get_stat, predict_prop_v1, CURRENT_SEASON, DATABASE
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
