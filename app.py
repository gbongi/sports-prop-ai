from flask import Flask, render_template, request, jsonify
import sqlite3
from main import get_player_games, predict_prop_v1, CURRENT_SEASON, DATABASE
from mlb_model import (
    analyze_mlb, HITTER_PROPS, PITCHER_PROPS,
    mlb_teams, mlb_team_roster, mlb_pregame_game_context, analyze_mlb_verified
)

app = Flask(__name__)
WNBA_PROPS = ["points","rebounds","assists","3pm","pra","ra","pa","pr","minutes"]

def wnba_teams():
    con = sqlite3.connect(DATABASE)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT DISTINCT team FROM player_games WHERE season=? AND team IS NOT NULL ORDER BY team",
        (CURRENT_SEASON,)
    ).fetchall()
    con.close()
    return [{"id":r["team"],"name":r["team"],"abbreviation":r["team"]} for r in rows]

def wnba_roster(team):
    con = sqlite3.connect(DATABASE)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT player, MAX(date) last_date
           FROM player_games
           WHERE season=? AND UPPER(team)=UPPER(?)
           GROUP BY player ORDER BY player""",
        (CURRENT_SEASON, team)
    ).fetchall()
    con.close()
    return [{"id":r["player"],"name":r["player"],"position":""} for r in rows]

@app.get("/api/teams")
def api_teams():
    sport = request.args.get("sport","WNBA").upper()
    try:
        return jsonify(mlb_teams() if sport == "MLB" else wnba_teams())
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.get("/api/players")
def api_players():
    sport = request.args.get("sport","WNBA").upper()
    team = request.args.get("team","")
    if not team:
        return jsonify([])
    try:
        return jsonify(mlb_team_roster(int(team)) if sport == "MLB" else wnba_roster(team))
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.get("/api/mlb-context")
def api_mlb_context():
    team = request.args.get("team")
    opponent = request.args.get("opponent")
    if not team:
        return jsonify([])
    try:
        return jsonify(mlb_pregame_game_context(team, opponent or None))
    except Exception as e:
        return jsonify({"error":str(e)}), 500


@app.get("/api/mlb-matchup")
def api_mlb_matchup():
    team = request.args.get("team", "")
    opponent = request.args.get("opponent", "")
    if not team or not opponent:
        return jsonify({
            "found": False,
            "message": "Select both teams."
        })
    try:
        games = mlb_pregame_game_context(int(team), int(opponent))
        if not games:
            return jsonify({
                "found": False,
                "message": "No matching MLB game found today.",
                "team_probable": None,
                "opponent_probable": None
            })
        g = games[0]
        # Determine selected team's side from the team lists.
        teams = mlb_teams()
        selected = next((t for t in teams if str(t["id"]) == str(team)), None)
        selected_name = selected["name"] if selected else None

        if selected_name == g.get("home"):
            team_probable = g.get("home_probable")
            opponent_probable = g.get("away_probable")
        else:
            team_probable = g.get("away_probable")
            opponent_probable = g.get("home_probable")

        return jsonify({
            "found": True,
            "status": g.get("status"),
            "away": g.get("away"),
            "home": g.get("home"),
            "team_probable": team_probable,
            "opponent_probable": opponent_probable
        })
    except Exception as e:
        return jsonify({"found": False, "message": str(e)}), 500

@app.route("/", methods=["GET","POST"])
def index():
    result = None
    error = None
    context = None
    form = {
        "sport":"WNBA","player_type":"hitter","team":"","player":"",
        "prop":"points","line":"","opponent":"","spread":""
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
                pred = predict_prop_v1(games, form["prop"], line, opponent, spread)
                if pred is None:
                    raise ValueError("Not enough WNBA games for a prediction.")
                result = pred
                result.update({
                    "sport":"WNBA","player":games[0]["player"],
                    "prop":form["prop"].upper(),"line":line,"opponent":opponent
                })
            else:
                # MLB dropdown values use team IDs. Resolve opponent name for H2H text matching.
                teams = mlb_teams()
                opp_obj = next((t for t in teams if str(t["id"]) == str(form["opponent"])), None)
                opponent_name = opp_obj["name"] if opp_obj else None
                result = analyze_mlb_verified(
                    form["player"], form["player_type"], form["prop"], line,
                    int(form["team"]), int(form["opponent"]), opponent_name
                )
                result["sport"] = "MLB"
                context = mlb_pregame_game_context(
                    int(form["team"]),
                    int(form["opponent"]) if form["opponent"] else None
                )
        except Exception as e:
            error = str(e)

    return render_template(
        "index.html", form=form, result=result, error=error, context=context,
        wnba_props=WNBA_PROPS, hitter_props=HITTER_PROPS,
        pitcher_props=PITCHER_PROPS
    )

if __name__ == "__main__":
    app.run(debug=True)
