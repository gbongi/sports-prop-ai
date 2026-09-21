from data.wnba_injuries import get_wnba_injuries, parse_injuries

import sys
import sqlite3
import statistics
from pathlib import Path


DATABASE = Path(__file__).resolve().parent / "database" / "wnba.db"
CURRENT_SEASON = 2026
TEAM_NAMES = {
    "ATL": "Atlanta Dream",
    "CHI": "Chicago Sky",
    "CON": "Connecticut Sun",
    "DAL": "Dallas Wings",
    "GS": "Golden State Valkyries",
    "IND": "Indiana Fever",
    "LA": "Los Angeles Sparks",
    "LV": "Las Vegas Aces",
    "MIN": "Minnesota Lynx",
    "NY": "New York Liberty",
    "PHX": "Phoenix Mercury",
    "POR": "Portland Fire",
    "SEA": "Seattle Storm",
    "TOR": "Toronto Tempo",
    "WSH": "Washington Mystics"
}

# ==========================================================
# DATABASE
# ==========================================================

def get_player_games(player_name, season=None):

    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    if season is not None:

        cursor.execute(
            """
            SELECT *
            FROM player_games
            WHERE LOWER(player) LIKE LOWER(?)
            AND season = ?
            ORDER BY date ASC
            """,
            (f"%{player_name}%", season)
        )

    else:

        cursor.execute(
            """
            SELECT *
            FROM player_games
            WHERE LOWER(player) LIKE LOWER(?)
            ORDER BY date ASC
            """,
            (f"%{player_name}%",)
        )

    games = cursor.fetchall()

    connection.close()

    return games


# ==========================================================
# PROP VALUES
# ==========================================================

def get_stat(game, prop):

    prop = prop.lower()

    if prop == "points":
        return game["points"]

    if prop == "rebounds":
        return game["rebounds"]

    if prop == "assists":
        return game["assists"]

    if prop == "3pm":
        return game["three_pm"]

    if prop == "pra":

        if (
            game["points"] is None
            or game["rebounds"] is None
            or game["assists"] is None
        ):
            return None

        return (
            game["points"]
            + game["rebounds"]
            + game["assists"]
        )

    if prop == "ra":

        if (
            game["rebounds"] is None
            or game["assists"] is None
        ):
            return None

        return (
            game["rebounds"]
            + game["assists"]
        )

    if prop == "pa":

        if (
            game["points"] is None
            or game["assists"] is None
        ):
            return None

        return (
            game["points"]
            + game["assists"]
        )

    if prop == "pr":

        if (
            game["points"] is None
            or game["rebounds"] is None
        ):
            return None

        return (
            game["points"]
            + game["rebounds"]
        )

    if prop == "minutes":
        return game["minutes"]

    return None


# ==========================================================
# WINDOW ANALYSIS
# ==========================================================

def calculate_window(games, prop, amount):

    sample = games[-amount:]

    values = [
        get_stat(game, prop)
        for game in sample
    ]

    values = [
        value
        for value in values
        if value is not None
    ]

    if not values:
        return None

    return {
        "average": statistics.mean(values),
        "median": statistics.median(values),
        "values": values
    }


# ==========================================================
# DISPLAY PLAYER PROP
# ==========================================================

def display_prop(games, prop):

    season = calculate_window(
        games,
        prop,
        len(games)
    )

    l20 = calculate_window(games, prop, 20)
    l10 = calculate_window(games, prop, 10)
    l5 = calculate_window(games, prop, 5)

    print()
    print(prop.upper())
    print("-" * 45)

    if season:
        print(
            "Season:",
            round(season["average"], 2)
        )

    if l20:
        print(
            "L20:   ",
            round(l20["average"], 2)
        )

    if l10:
        print(
            "L10:   ",
            round(l10["average"], 2)
        )

    if l5:
        print(
            "L5:    ",
            round(l5["average"], 2)
        )

        print(
            "Last 5:",
            l5["values"]
        )


# ==========================================================
# FULL PLAYER REPORT
# ==========================================================

def analyze_player(player_name, season=CURRENT_SEASON):

    games = get_player_games(
        player_name,
        season
    )

    if not games:

        print()
        print(
            f"No games found for '{player_name}' in {season}"
        )

        return

    actual_name = games[0]["player"]
    team = games[-1]["team"]

    print()
    print("=" * 55)

    print(
        actual_name.upper(),
        "-",
        season
    )

    print("=" * 55)

    print("Team:", team)
    print("Games:", len(games))

    props = [
        "points",
        "rebounds",
        "assists",
        "3pm",
        "pra",
        "ra",
        "pa",
        "pr",
        "minutes"
    ]

    for prop in props:
        display_prop(games, prop)

    print()
    print("=" * 55)
    print("LAST 5 GAMES")
    print("=" * 55)

    for game in games[-5:]:

        pra = (
            (game["points"] or 0)
            + (game["rebounds"] or 0)
            + (game["assists"] or 0)
        )

        location = (
            "vs"
            if str(game["home_away"]).upper() == "HOME"
            else "@"
        )

        print()

        print(
            game["date"],
            location,
            game["opponent"]
        )

        print(
            "MIN:",
            game["minutes"],
            "| PTS:",
            game["points"],
            "| REB:",
            game["rebounds"],
            "| AST:",
            game["assists"],
            "| PRA:",
            pra
        )


# ==========================================================
# PROP LINE ANALYSIS
# ==========================================================

def analyze_line(games, prop, line):

    values = [
        get_stat(game, prop)
        for game in games
    ]

    values = [
        value
        for value in values
        if value is not None
    ]

    if not values:

        print(
            f"No data available for prop '{prop}'."
        )

        return

    print()
    print("=" * 55)
    print(
        f"PROP LINE ANALYSIS: {prop.upper()} {line}"
    )
    print("=" * 55)

    windows = {
        "Season": values,
        "L20": values[-20:],
        "L10": values[-10:],
        "L5": values[-5:]
    }

    for name, sample in windows.items():

        more = sum(
            value > line
            for value in sample
        )

        less = sum(
            value < line
            for value in sample
        )

        push = sum(
            value == line
            for value in sample
        )

        total = len(sample)

        more_rate = (
            more / total * 100
        )

        less_rate = (
            less / total * 100
        )

        print()
        print(name)

        print(
            f"MORE: {more}/{total}",
            f"({more_rate:.1f}%)"
        )

        print(
            f"LESS: {less}/{total}",
            f"({less_rate:.1f}%)"
        )

        if push:
            print(
                f"PUSH: {push}/{total}"
            )

    # ------------------------------------------------------
    # CURRENT STREAK
    # ------------------------------------------------------

    streak_direction = None
    streak = 0

    for value in reversed(values):

        if value > line:
            result = "MORE"

        elif value < line:
            result = "LESS"

        else:
            result = "PUSH"

        if result == "PUSH":
            break

        if streak_direction is None:

            streak_direction = result
            streak = 1

        elif result == streak_direction:

            streak += 1

        else:
            break

    print()
    print("CURRENT STREAK:")

    if streak_direction:
        print(
            streak_direction,
            streak
        )
    else:
        print("NONE")

    # ------------------------------------------------------
    # LAST 10
    # ------------------------------------------------------

    print()
    print("LAST 10")

    for value in values[-10:]:

        if value > line:
            result = "MORE"

        elif value < line:
            result = "LESS"

        else:
            result = "PUSH"

        print(
            value,
            "->",
            result
        )


# ==========================================================
# MINUTES / OPPORTUNITY / ROLE
# ==========================================================

def analyze_opportunity(games):

    print()
    print("=" * 55)
    print("MINUTES / OPPORTUNITY / ROLE")
    print("=" * 55)

    def avg(sample, field):

        values = [
            game[field]
            for game in sample
            if game[field] is not None
        ]

        if not values:
            return None

        return statistics.mean(values)

    windows = {
        "Season": games,
        "L20": games[-20:],
        "L10": games[-10:],
        "L5": games[-5:]
    }

    # ------------------------------------------------------
    # BASIC OPPORTUNITY
    # ------------------------------------------------------

    print()

    print(
        f"{'WINDOW':<10}"
        f"{'MIN':>8}"
        f"{'FGA':>8}"
        f"{'FTA':>8}"
        f"{'3PA':>8}"
    )

    print("-" * 42)

    for name, sample in windows.items():

        minutes = avg(
            sample,
            "minutes"
        )

        fga = avg(
            sample,
            "fg_attempts"
        )

        fta = avg(
            sample,
            "ft_attempts"
        )

        three_pa = avg(
            sample,
            "three_pa"
        )

        if None in (
            minutes,
            fga,
            fta,
            three_pa
        ):
            continue

        print(
            f"{name:<10}"
            f"{minutes:>8.2f}"
            f"{fga:>8.2f}"
            f"{fta:>8.2f}"
            f"{three_pa:>8.2f}"
        )

    # ------------------------------------------------------
    # STARTER RATE
    # ------------------------------------------------------

    print()
    print("STARTER RATE")
    print("-" * 42)

    for name, sample in windows.items():

        starters = [
            game["starter"]
            for game in sample
            if game["starter"] is not None
        ]

        if not starters:
            continue

        starter_rate = (
            sum(starters)
            / len(starters)
            * 100
        )

        print(
            f"{name:<10}"
            f"{starter_rate:>7.1f}%"
        )

    # ------------------------------------------------------
    # PRODUCTION PER MINUTE
    # ------------------------------------------------------

    print()
    print("PRODUCTION PER MINUTE")
    print("-" * 55)

    print(
        f"{'WINDOW':<10}"
        f"{'PTS/M':>10}"
        f"{'REB/M':>10}"
        f"{'AST/M':>10}"
    )

    for name, sample in windows.items():

        valid_games = [
            game
            for game in sample
            if game["minutes"] is not None
            and game["minutes"] > 0
        ]

        if not valid_games:
            continue

        total_minutes = sum(
            game["minutes"]
            for game in valid_games
        )

        total_points = sum(
            game["points"] or 0
            for game in valid_games
        )

        total_rebounds = sum(
            game["rebounds"] or 0
            for game in valid_games
        )

        total_assists = sum(
            game["assists"] or 0
            for game in valid_games
        )

        print(
            f"{name:<10}"
            f"{total_points / total_minutes:>10.3f}"
            f"{total_rebounds / total_minutes:>10.3f}"
            f"{total_assists / total_minutes:>10.3f}"
        )

    # ------------------------------------------------------
    # ROLE TREND
    # ------------------------------------------------------

    season_minutes = avg(
        games,
        "minutes"
    )

    l5_minutes = avg(
        games[-5:],
        "minutes"
    )

    season_fga = avg(
        games,
        "fg_attempts"
    )

    l5_fga = avg(
        games[-5:],
        "fg_attempts"
    )

    print()
    print("ROLE TREND")
    print("-" * 42)

    if (
        season_minutes is None
        or l5_minutes is None
        or season_fga is None
        or l5_fga is None
    ):

        print(
            "Not enough data for role trend."
        )

        return

    minute_change = (
        l5_minutes
        - season_minutes
    )

    fga_change = (
        l5_fga
        - season_fga
    )

    print(
        "Minutes change:",
        f"{minute_change:+.2f}"
    )

    print(
        "FGA change:    ",
        f"{fga_change:+.2f}"
    )

    if minute_change >= 3:

        print(
            "ROLE FLAG: Increased recent playing time"
        )

    elif minute_change <= -3:

        print(
            "ROLE FLAG: Decreased recent playing time"
        )

    else:

        print(
            "ROLE FLAG: Playing time relatively stable"
        )

    if fga_change >= 2:

        print(
            "USAGE FLAG: Shooting opportunity increased"
        )

    elif fga_change <= -2:

        print(
            "USAGE FLAG: Shooting opportunity decreased"
        )

    else:

        print(
            "USAGE FLAG: Shooting opportunity relatively stable"
        )


# ==========================================================
# HOME / AWAY + REST CONTEXT
# ==========================================================

def analyze_context(games, prop, line, opponent=None):

    print()
    print("=" * 55)
    print("GAME CONTEXT")
    print("=" * 55)

    # ------------------------------------------------------
    # HOME / AWAY
    # ------------------------------------------------------

    print()
    print("HOME / AWAY")
    print("-" * 45)

    for location in [
        "HOME",
        "AWAY"
    ]:

        sample = [
            game
            for game in games
            if str(
                game["home_away"]
            ).upper() == location
        ]

        values = [
            get_stat(
                game,
                prop
            )
            for game in sample
        ]

        values = [
            value
            for value in values
            if value is not None
        ]

        if not values:
            continue

        average = statistics.mean(
            values
        )

        median = statistics.median(
            values
        )

        more = sum(
            value > line
            for value in values
        )

        less = sum(
            value < line
            for value in values
        )

        push = sum(
            value == line
            for value in values
        )

        total = len(values)

        print()
        print(location)

        print(
            "Games:",
            total
        )

        print(
            "Average:",
            round(
                average,
                2
            )
        )

        print(
            "Median:",
            round(
                median,
                2
            )
        )

        print(
            f"MORE {line}:",
            f"{more}/{total}",
            f"({more / total * 100:.1f}%)"
        )

        print(
            f"LESS {line}:",
            f"{less}/{total}",
            f"({less / total * 100:.1f}%)"
        )

        if push:
            print(
                "PUSH:",
                push
            )

    # ------------------------------------------------------
    # REST ANALYSIS
    # ------------------------------------------------------

    print()
    print("REST ANALYSIS")
    print("-" * 45)

    rest_groups = {
        "Back-to-back": [],
        "1 day rest": [],
        "2 days rest": [],
        "3+ days rest": []
    }

    for game in games:

        rest = game["days_rest"]

        if rest is None:
            continue

        if rest <= 0:

            group = "Back-to-back"

        elif rest == 1:

            group = "1 day rest"

        elif rest == 2:

            group = "2 days rest"

        else:

            group = "3+ days rest"

        rest_groups[group].append(
            game
        )

    for name, sample in rest_groups.items():

        values = [
            get_stat(
                game,
                prop
            )
            for game in sample
        ]

        values = [
            value
            for value in values
            if value is not None
        ]

        if not values:
            continue

        total = len(values)

        average = statistics.mean(
            values
        )

        median = statistics.median(
            values
        )

        more = sum(
            value > line
            for value in values
        )

        less = sum(
            value < line
            for value in values
        )

        push = sum(
            value == line
            for value in values
        )

        print()
        print(name)

        print(
            "Games:",
            total
        )

        print(
            "Average:",
            round(
                average,
                2
            )
        )

        print(
            "Median:",
            round(
                median,
                2
            )
        )

        print(
            f"MORE {line}:",
            f"{more}/{total}",
            f"({more / total * 100:.1f}%)"
        )

        print(
            f"LESS {line}:",
            f"{less}/{total}",
            f"({less / total * 100:.1f}%)"
        )

        if push:
            print(
                "PUSH:",
                push
            )

    # ------------------------------------------------------
    # CURRENT-SEASON OPPONENT SUMMARY
    # ------------------------------------------------------

    if opponent:

        opponent = opponent.upper()

        matchup_games = [
            game
            for game in games
            if str(
                game["opponent"]
            ).upper() == opponent
        ]

        print()
        print(
            f"{CURRENT_SEASON} VS {opponent}"
        )
        print("-" * 45)

        if not matchup_games:

            print(
                f"No {CURRENT_SEASON} games found vs {opponent}."
            )

        else:

            values = [
                get_stat(
                    game,
                    prop
                )
                for game in matchup_games
            ]

            values = [
                value
                for value in values
                if value is not None
            ]

            if values:

                print(
                    "Games:",
                    len(values)
                )

                print(
                    "Average:",
                    round(
                        statistics.mean(values),
                        2
                    )
                )

                print(
                    "Median:",
                    round(
                        statistics.median(values),
                        2
                    )
                )


# ==========================================================
# MATCHUP HISTORY
# ==========================================================

def analyze_matchup(
    games,
    prop,
    line,
    opponent
):

    opponent = opponent.upper()

    matchup_games = [
        game
        for game in games
        if str(
            game["opponent"]
        ).upper() == opponent
    ]

    print()
    print("=" * 55)
    print(
        f"MATCHUP HISTORY VS {opponent}"
    )
    print("=" * 55)

    if not matchup_games:

        print(
            f"No matchup games found vs {opponent}."
        )

        return

    values = [
        get_stat(
            game,
            prop
        )
        for game in matchup_games
    ]

    values = [
        value
        for value in values
        if value is not None
    ]

    if not values:

        print(
            "No valid prop data found."
        )

        return

    average = statistics.mean(
        values
    )

    median = statistics.median(
        values
    )

    more = sum(
        value > line
        for value in values
    )

    less = sum(
        value < line
        for value in values
    )

    push = sum(
        value == line
        for value in values
    )

    total = len(values)

    print(
        "Games:",
        total
    )

    print(
        "Average:",
        round(
            average,
            2
        )
    )

    print(
        "Median:",
        round(
            median,
            2
        )
    )

    print()

    print(
        f"MORE {line}:",
        f"{more}/{total}",
        f"({more / total * 100:.1f}%)"
    )

    print(
        f"LESS {line}:",
        f"{less}/{total}",
        f"({less / total * 100:.1f}%)"
    )

    if push:
        print(
            "PUSH:",
            push
        )

    print()
    print("GAME-BY-GAME")

    for game in matchup_games:

        value = get_stat(
            game,
            prop
        )

        if value is None:
            continue

        if value > line:

            result = "MORE"

        elif value < line:

            result = "LESS"

        else:

            result = "PUSH"

        location = (
            "vs"
            if str(
                game["home_away"]
            ).upper() == "HOME"
            else "@"
        )

        print(
            game["date"],
            location,
            opponent,
            "|",
            prop.upper(),
            value,
            "|",
            result,
            "| MIN",
            game["minutes"]
        )


# ==========================================================
# INJURED PLAYER ROLE IMPORTANCE
# ==========================================================

def get_player_importance(player_name, season=CURRENT_SEASON):

    games = get_player_games(
        player_name,
        season=season
    )

    if not games:
        return None

    def average(field):

        values = [
            game[field]
            for game in games
            if game[field] is not None
        ]

        if not values:
            return 0

        return statistics.mean(values)

    avg_minutes = average("minutes")
    avg_points = average("points")
    avg_rebounds = average("rebounds")
    avg_assists = average("assists")
    avg_fga = average("fg_attempts")

    starters = [
        game["starter"]
        for game in games
        if game["starter"] is not None
    ]

    if starters:
        starter_rate = (
            sum(starters)
            / len(starters)
            * 100
        )
    else:
        starter_rate = 0

    # This is a role-size classification only.
    # It is NOT yet a MORE/LESS injury adjustment.
    if (
        avg_minutes >= 28
        or starter_rate >= 75
    ):
        importance = "HIGH"

    elif (
        avg_minutes >= 18
        or starter_rate >= 35
    ):
        importance = "MEDIUM"

    else:
        importance = "LOW"

    return {
        "games": len(games),
        "minutes": avg_minutes,
        "starter_rate": starter_rate,
        "points": avg_points,
        "rebounds": avg_rebounds,
        "assists": avg_assists,
        "fga": avg_fga,
        "importance": importance
    }


def display_injured_player(injury):

    print()

    print(
        injury["player"],
        "|",
        injury["status"],
        "|",
        injury["injury"]
    )

    importance = get_player_importance(
        injury["player"]
    )

    if importance is None:

        print(
            "2026 database role data unavailable"
        )

        return

    print(
        f"Games: {importance['games']}"
    )

    print(
        f"MIN: {importance['minutes']:.1f}",
        "|",
        f"Starter: {importance['starter_rate']:.1f}%"
    )

    print(
        f"PTS: {importance['points']:.1f}",
        "|",
        f"REB: {importance['rebounds']:.1f}",
        "|",
        f"AST: {importance['assists']:.1f}"
    )

    print(
        f"FGA: {importance['fga']:.1f}"
    )

    print(
        "ROLE IMPORTANCE:",
        importance["importance"]
    )


def analyze_injuries(
    games,
    player_name,
    opponent=None
):

    print()
    print("=" * 55)
    print("INJURY / AVAILABILITY CONTEXT")
    print("=" * 55)

    # ---------------------------------------------
    # DOWNLOAD CURRENT INJURIES
    # ---------------------------------------------

    data = get_wnba_injuries()

    if not data:

        print(
            "Current injury data unavailable."
        )

        return

    injuries = parse_injuries(data)

    if not injuries:

        print(
            "No current injury data returned."
        )

        return

    # ---------------------------------------------
    # CURRENT PLAYER TEAM
    # ---------------------------------------------

    team_abbr = str(
        games[-1]["team"]
    ).upper()

    team_name = TEAM_NAMES.get(
        team_abbr,
        team_abbr
    )

    # ---------------------------------------------
    # PLAYER STATUS
    # ---------------------------------------------

    print()
    print("PLAYER STATUS")
    print("-" * 45)

    player_injury = None

    for injury in injuries:

        if (
            injury["player"].lower()
            == player_name.lower()
        ):

            player_injury = injury
            break

    if player_injury:

        print(
            player_injury["player"],
            "|",
            player_injury["status"],
            "|",
            player_injury["injury"]
        )

        if player_injury["detail"]:

            print(
                "Detail:",
                player_injury["detail"]
            )

    else:

        print(
            games[0]["player"],
            "| No current injury listing"
        )

    # ---------------------------------------------
    # TEAMMATE INJURIES
    # ---------------------------------------------

    print()
    print(
        f"{team_name.upper()} TEAMMATES"
    )
    print("-" * 45)

    teammate_injuries = [
        injury
        for injury in injuries
        if injury["team"] == team_name
        and injury["player"].lower()
        != player_name.lower()
    ]

    if not teammate_injuries:

        print(
            "No teammates currently listed."
        )

    else:

        for injury in teammate_injuries:

            display_injured_player(
                injury
            )

            if injury["detail"]:

                print(
                    "Detail:",
                    injury["detail"]
                )

    # ---------------------------------------------
    # OPPONENT INJURIES
    # ---------------------------------------------

    if opponent:

        opponent = opponent.upper()

        opponent_name = TEAM_NAMES.get(
            opponent,
            opponent
        )

        print()
        print(
            f"{opponent_name.upper()} INJURIES"
        )
        print("-" * 45)

        opponent_injuries = [
            injury
            for injury in injuries
            if injury["team"] == opponent_name
        ]

        if not opponent_injuries:

            print(
                "No opponent injuries currently listed."
            )

        else:

            for injury in opponent_injuries:

                display_injured_player(
                    injury
                )

                if injury["detail"]:

                    print(
                        "Detail:",
                        injury["detail"]
                    )



# ==========================================================
# V2 CONTEXT HELPERS: OPPONENT + EXPECTED MINUTES + INJURIES
# ==========================================================

def _mean(values):
    vals = [float(v) for v in values if v is not None]
    return statistics.mean(vals) if vals else None


def _team_rows(team, season=CURRENT_SEASON):
    con = sqlite3.connect(DATABASE)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM player_games WHERE UPPER(team)=UPPER(?) AND season=? ORDER BY date ASC",
        (team, season),
    )
    rows = cur.fetchall()
    con.close()
    return rows


def _rows_vs_team(team, season=CURRENT_SEASON):
    con = sqlite3.connect(DATABASE)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM player_games WHERE UPPER(opponent)=UPPER(?) AND season=? ORDER BY date ASC",
        (team, season),
    )
    rows = cur.fetchall()
    con.close()
    return rows


def _aggregate_team_games(rows):
    games = {}
    fields = ("points","rebounds","assists","fg_attempts","fg_made","ft_attempts","three_pa","three_pm")
    for r in rows:
        gid = r["game_id"]
        if gid not in games:
            games[gid] = {f: 0.0 for f in fields}
        for f in fields:
            if r[f] is not None:
                games[gid][f] += float(r[f])
    return list(games.values())


def opponent_profile(opponent):
    """Same-season team environment. Does not invent position/tracking data."""
    own = _aggregate_team_games(_team_rows(opponent))
    allowed = _aggregate_team_games(_rows_vs_team(opponent))
    if not own or not allowed:
        return None

    fg_allowed = [
        g["fg_made"]/g["fg_attempts"]
        for g in allowed if g["fg_attempts"] > 0
    ]
    misses = [max(0.0, g["fg_attempts"]-g["fg_made"]) for g in own]
    pace_proxy = [g["fg_attempts"] + 0.44*g["ft_attempts"] for g in own]

    return {
        "games": len(own),
        "points_allowed": _mean([g["points"] for g in allowed]),
        "rebounds_allowed": _mean([g["rebounds"] for g in allowed]),
        "assists_allowed": _mean([g["assists"] for g in allowed]),
        "three_pm_allowed": _mean([g["three_pm"] for g in allowed]),
        "fg_pct_allowed": _mean(fg_allowed),
        "missed_fg": _mean(misses),
        "pace_proxy": _mean(pace_proxy),
    }


_LEAGUE_ALLOWED_CACHE = {}


def league_allowed_average(prop):
    # These league averages are identical for every prediction while
    # the process is running, so calculate each prop once and reuse it.
    if prop in _LEAGUE_ALLOWED_CACHE:
        return _LEAGUE_ALLOWED_CACHE[prop]

    field = {
        "points": "points",
        "rebounds": "rebounds",
        "assists": "assists",
        "3pm": "three_pm",
    }.get(prop)

    if not field:
        return None

    con = sqlite3.connect(DATABASE)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT game_id, opponent, points, rebounds, assists, three_pm
        FROM player_games
        WHERE season=?
        """,
        (CURRENT_SEASON,),
    ).fetchall()
    con.close()

    grouped = {}

    for r in rows:
        key = (r["game_id"], r["opponent"])

        if key not in grouped:
            grouped[key] = {
                "points": 0.0,
                "rebounds": 0.0,
                "assists": 0.0,
                "three_pm": 0.0,
            }

        for f in grouped[key]:
            if r[f] is not None:
                grouped[key][f] += float(r[f])

    value = _mean([
        game[field]
        for game in grouped.values()
    ])

    _LEAGUE_ALLOWED_CACHE[prop] = value
    return value


def opponent_adjustment(opponent, prop):
    profile = opponent_profile(opponent)
    if not profile:
        return 1.0, "UNKNOWN", None

    fields = {
        "points":[("points_allowed","points")],
        "rebounds":[("rebounds_allowed","rebounds")],
        "assists":[("assists_allowed","assists")],
        "3pm":[("three_pm_allowed","3pm")],
        "pra":[("points_allowed","points"),("rebounds_allowed","rebounds"),("assists_allowed","assists")],
        "ra":[("rebounds_allowed","rebounds"),("assists_allowed","assists")],
        "pa":[("points_allowed","points"),("assists_allowed","assists")],
        "pr":[("points_allowed","points"),("rebounds_allowed","rebounds")],
    }.get(prop, [])

    ratios = []
    for key, base_prop in fields:
        league = league_allowed_average(base_prop)
        value = profile.get(key)
        if league and value is not None:
            ratios.append(value/league)

    if not ratios:
        return 1.0, "UNKNOWN", profile

    # Heavy shrinkage: opponent team environment is useful but should not dominate.
    raw = statistics.mean(ratios)
    mult = 1.0 + 0.20*(raw-1.0)
    mult = max(0.95, min(1.05, mult))
    label = "FAVORABLE" if mult >= 1.015 else "DIFFICULT" if mult <= 0.985 else "NEUTRAL"
    return mult, label, profile


def expected_minutes_context(games, player_name):
    """Estimate current minutes from long/recent role plus current teammate absences."""
    mins = [float(g["minutes"]) for g in games if g["minutes"] is not None]
    if not mins:
        return None

    season_min = statistics.mean(mins)
    recent = statistics.mean(mins[-5:]) if len(mins) >= 5 else statistics.mean(mins)
    # Recent role matters, but regression keeps L5 from dominating.
    expected = 0.65*season_min + 0.35*recent

    injuries_used = []
    try:
        raw = get_wnba_injuries()
        injuries = parse_injuries(raw) if raw else []
    except Exception:
        injuries = []

    team_abbr = str(games[-1]["team"]).upper()
    team_name = TEAM_NAMES.get(team_abbr, team_abbr)

    for inj in injuries:
        if inj.get("team") != team_name:
            continue
        if inj.get("player","").lower() == player_name.lower():
            continue

        status = str(inj.get("status","")).lower()
        if not any(x in status for x in ("out","doubtful")):
            continue

        importance = get_player_importance(inj["player"])
        if not importance:
            continue

        # Conservative opportunity redistribution. We do NOT assume all vacated
        # minutes go to the player being analyzed.
        if importance["importance"] == "HIGH":
            bump = 0.8
        elif importance["importance"] == "MEDIUM":
            bump = 0.4
        else:
            bump = 0.15

        injuries_used.append({
            "player": inj["player"],
            "status": inj["status"],
            "importance": importance["importance"],
            "minutes_bump": bump,
        })

    # Multiple teammate absences should not be assumed to transfer
    # all of their opportunity to the player being analyzed.
    #
    # Add the conservative individual estimates, but cap the total
    # injury-driven minutes increase at +1.5 minutes.
    total_injury_bump = sum(
        item["minutes_bump"]
        for item in injuries_used
    )

    total_injury_bump = min(
        1.5,
        total_injury_bump
    )

    expected += total_injury_bump

    # Avoid unrealistic minutes.
    expected = max(0.0, min(40.0, expected))
    return {
        "season_minutes": season_min,
        "recent_minutes": recent,
        "expected_minutes": expected,
        "injuries_used": injuries_used,
    }


def display_v2_context(games, player_name, prop, opponent=None):
    print()
    print("="*55)
    print("V2 PREGAME CONTEXT")
    print("="*55)

    m = expected_minutes_context(games, player_name)
    if m:
        print(f"Season minutes: {m['season_minutes']:.1f}")
        print(f"Recent minutes: {m['recent_minutes']:.1f}")
        print(f"Expected minutes: {m['expected_minutes']:.1f}")
        if m["injuries_used"]:
            print("Teammate availability affecting minutes estimate:")
            for item in m["injuries_used"]:
                print(
                    f"  {item['player']} | {item['status']} | "
                    f"{item['importance']} role | {item['minutes_bump']:+.2f} min"
                )
        else:
            print("No OUT/DOUBTFUL teammate adjustment applied.")

    if opponent:
        mult, label, p = opponent_adjustment(opponent, prop)
        print()
        print(f"Opponent matchup: {label}")
        print(f"Opponent multiplier: {mult:.3f}x")
        if p:
            if p["pace_proxy"] is not None:
                print(f"Pace proxy: {p['pace_proxy']:.1f}")
            if p["fg_pct_allowed"] is not None:
                print(f"FG% allowed: {100*p['fg_pct_allowed']:.1f}%")
            if p["missed_fg"] is not None:
                print(f"Opponent missed FGs/game: {p['missed_fg']:.1f}")
            if p["rebounds_allowed"] is not None:
                print(f"Team rebounds allowed/game: {p['rebounds_allowed']:.1f}")
            if p["assists_allowed"] is not None:
                print(f"Team assists allowed/game: {p['assists_allowed']:.1f}")
            if p["points_allowed"] is not None:
                print(f"Team points allowed/game: {p['points_allowed']:.1f}")

        print(
            "Position-specific defense / individual assignments are not "
            "invented because the current DB does not contain reliable tracking labels."
        )



# ==========================================================
# PREDICTION MODEL V1
# ==========================================================

def predict_prop_v1(games, prop, line, opponent=None, spread=None):

    # ======================================================
    # WNBA V2 CALIBRATED PROP MODEL
    # ======================================================
    #
    # Goals:
    # - Do not let L5 hot/cold streaks dominate.
    # - Require agreement across multiple time windows.
    # - Combine distribution probability with actual hit rates.
    # - Penalize disagreement and unstable roles.
    # - Keep matchup/minutes/blowout adjustments conservative.
    # - Avoid fake HIGH confidence from a single normal curve.
    # ======================================================

    import math

    valid = []

    for game in games:

        value = get_stat(
            game,
            prop
        )

        if value is not None:

            valid.append(
                (
                    game,
                    float(value),
                )
            )

    if len(valid) < 8:
        return None

    values = [
        value
        for _, value in valid
    ]

    n = len(values)

    # ------------------------------------------------------
    # MULTI-HORIZON BASELINES
    # ------------------------------------------------------

    season_values = values

    l20_values = values[-20:]

    l10_values = values[-10:]

    l5_values = values[-5:]

    season_avg = statistics.mean(
        season_values
    )

    l20_avg = statistics.mean(
        l20_values
    )

    l10_avg = statistics.mean(
        l10_values
    )

    l5_avg = statistics.mean(
        l5_values
    )

    # Larger samples deliberately receive more influence.
    #
    # L5 is useful for role/form detection but is NOT allowed
    # to drive the projection by itself.
    projection = (
        season_avg * 0.45
        + l20_avg * 0.30
        + l10_avg * 0.20
        + l5_avg * 0.05
    )

    projection_before_h2h = (
        projection
    )

    # ------------------------------------------------------
    # OPPONENT H2H — SMALL SECONDARY SIGNAL
    # ------------------------------------------------------

    h2h_values = []

    if opponent:

        opponent = opponent.upper()

        h2h_values = [
            float(
                get_stat(
                    game,
                    prop
                )
            )
            for game, _ in valid
            if (
                str(
                    game["opponent"]
                ).upper()
                == opponent
                and get_stat(
                    game,
                    prop
                )
                is not None
            )
        ]

        if h2h_values:

            h2h_mean = (
                statistics.mean(
                    h2h_values
                )
            )

            # Smaller maximum than V1.
            # H2H samples are often tiny.
            h2h_weight = min(
                0.10,
                len(h2h_values)
                / 40.0,
            )

            projection = (
                projection
                * (
                    1.0
                    - h2h_weight
                )
                + h2h_mean
                * h2h_weight
            )

    # ------------------------------------------------------
    # EXPECTED MINUTES / ROLE
    # ------------------------------------------------------

    projection_before_minutes = (
        projection
    )

    minutes_context = (
        expected_minutes_context(
            games,
            games[0]["player"],
        )
    )

    role_minutes_multiplier = 1.0

    if (
        minutes_context
        and prop != "minutes"
    ):

        base_minutes = (
            minutes_context[
                "season_minutes"
            ]
        )

        if (
            base_minutes
            and base_minutes > 0
        ):

            raw_ratio = (
                minutes_context[
                    "expected_minutes"
                ]
                / base_minutes
            )

            # Conservative translation of minutes changes
            # into counting-stat changes.
            role_minutes_multiplier = (
                1.0
                + 0.50
                * (
                    raw_ratio
                    - 1.0
                )
            )

            role_minutes_multiplier = max(
                0.94,
                min(
                    1.06,
                    role_minutes_multiplier,
                ),
            )

            projection *= (
                role_minutes_multiplier
            )

    elif (
        minutes_context
        and prop == "minutes"
    ):

        projection = (
            minutes_context[
                "expected_minutes"
            ]
        )

    # ------------------------------------------------------
    # OPPONENT TEAM ENVIRONMENT
    # ------------------------------------------------------

    projection_before_matchup = (
        projection
    )

    matchup_multiplier = 1.0
    matchup_label = "UNKNOWN"
    matchup_profile_data = None

    if opponent:

        (
            matchup_multiplier,
            matchup_label,
            matchup_profile_data,
        ) = opponent_adjustment(
            opponent,
            prop,
        )

        projection *= (
            matchup_multiplier
        )

    # ------------------------------------------------------
    # BLOWOUT RISK
    # ------------------------------------------------------

    projection_before_blowout = (
        projection
    )

    blowout_level = "UNKNOWN"
    blowout_multiplier = 1.0
    blowout_minutes_factor = 1.0

    if spread is not None:

        abs_spread = abs(
            float(spread)
        )

        if abs_spread < 6:

            blowout_level = "LOW"
            blowout_minutes_factor = 1.00

        elif abs_spread < 10:

            blowout_level = "MODERATE"
            blowout_minutes_factor = 0.985

        elif abs_spread < 14:

            blowout_level = "HIGH"
            blowout_minutes_factor = 0.965

        else:

            blowout_level = "VERY HIGH"
            blowout_minutes_factor = 0.94

        if prop == "minutes":

            blowout_multiplier = (
                blowout_minutes_factor
            )

        elif prop in {
            "points",
            "rebounds",
            "assists",
            "3pm",
            "pra",
            "ra",
            "pa",
            "pr",
        }:

            blowout_multiplier = (
                1.0
                - (
                    (
                        1.0
                        - blowout_minutes_factor
                    )
                    * 0.80
                )
            )

        projection *= (
            blowout_multiplier
        )

    # ------------------------------------------------------
    # VOLATILITY
    # ------------------------------------------------------

    volatility_sample = (
        values[-20:]
    )

    if (
        len(volatility_sample)
        >= 2
    ):

        sigma = statistics.stdev(
            volatility_sample
        )

    else:

        sigma = 0.0

    # Prop-specific minimum uncertainty.
    #
    # Prevents an unusually consistent short sample from
    # producing unrealistic probabilities.
    sigma_floors = {
        "points": 3.0,
        "rebounds": 2.0,
        "assists": 1.5,
        "3pm": 1.0,
        "pra": 4.0,
        "ra": 2.5,
        "pa": 3.5,
        "pr": 3.5,
        "minutes": 2.0,
    }

    sigma = max(
        sigma,
        sigma_floors.get(
            prop,
            1.5,
        ),
    )

    # ------------------------------------------------------
    # NORMAL-DISTRIBUTION PROBABILITY
    # ------------------------------------------------------

    z = (
        float(line)
        - projection
    ) / sigma

    normal_less = (
        0.5
        * (
            1.0
            + math.erf(
                z
                / math.sqrt(2)
            )
        )
    )

    normal_more = (
        1.0
        - normal_less
    )

    # ------------------------------------------------------
    # EMPIRICAL HIT RATES
    # ------------------------------------------------------

    def more_rate(sample):

        if not sample:
            return 0.50

        return (
            sum(
                1
                for value
                in sample
                if value
                > float(line)
            )
            / len(sample)
        )

    season_more = more_rate(
        season_values
    )

    l20_more = more_rate(
        l20_values
    )

    l10_more = more_rate(
        l10_values
    )

    l5_more = more_rate(
        l5_values
    )

    # Again: recent games matter, but L5 cannot dominate.
    empirical_more = (
        season_more * 0.45
        + l20_more * 0.30
        + l10_more * 0.20
        + l5_more * 0.05
    )

    # ------------------------------------------------------
    # BLEND MODEL PROBABILITY + OBSERVED HIT RATE
    # ------------------------------------------------------

    # Empirical results receive slightly more weight because
    # many basketball prop distributions are not perfectly
    # normal.
    p_more = (
        empirical_more * 0.60
        + normal_more * 0.40
    )

    # ------------------------------------------------------
    # SAMPLE-SIZE RELIABILITY
    # ------------------------------------------------------

    reliability = min(
        1.0,
        n / 30.0,
    )

    p_more = (
        0.50
        + (
            p_more
            - 0.50
        )
        * reliability
    )

    # ------------------------------------------------------
    # MULTI-WINDOW AGREEMENT
    # ------------------------------------------------------

    window_avgs = [
        season_avg,
        l20_avg,
        l10_avg,
        l5_avg,
    ]

    window_sides = []

    for avg in window_avgs:

        if avg > float(line):
            window_sides.append(1)

        elif avg < float(line):
            window_sides.append(-1)

        else:
            window_sides.append(0)

    more_windows = sum(
        side == 1
        for side in window_sides
    )

    less_windows = sum(
        side == -1
        for side in window_sides
    )

    agreement_count = max(
        more_windows,
        less_windows,
    )

    # If historical windows disagree, confidence gets pulled
    # toward 50 rather than blindly following the projection.
    if agreement_count <= 2:

        disagreement_multiplier = 0.65

    elif agreement_count == 3:

        disagreement_multiplier = 0.85

    else:

        disagreement_multiplier = 1.0

    p_more = (
        0.50
        + (
            p_more
            - 0.50
        )
        * disagreement_multiplier
    )

    # ------------------------------------------------------
    # PROJECTION-vs-HIT-RATE DISAGREEMENT
    # ------------------------------------------------------

    projection_side = (
        1
        if projection > float(line)
        else -1
        if projection < float(line)
        else 0
    )

    empirical_side = (
        1
        if empirical_more > 0.50
        else -1
        if empirical_more < 0.50
        else 0
    )

    model_disagreement = (
        projection_side != 0
        and empirical_side != 0
        and projection_side
        != empirical_side
    )

    if model_disagreement:

        p_more = (
            0.50
            + (
                p_more
                - 0.50
            )
            * 0.72
        )

    # ------------------------------------------------------
    # ROLE INSTABILITY PENALTY
    # ------------------------------------------------------

    role_unstable = False

    if minutes_context:

        season_minutes = (
            minutes_context[
                "season_minutes"
            ]
        )

        recent_minutes = (
            minutes_context[
                "recent_minutes"
            ]
        )

        if (
            season_minutes
            and season_minutes > 0
        ):

            minutes_change = abs(
                recent_minutes
                - season_minutes
            ) / season_minutes

            if minutes_change >= 0.15:

                role_unstable = True

                p_more = (
                    0.50
                    + (
                        p_more
                        - 0.50
                    )
                    * 0.80
                )

    # ------------------------------------------------------
    # FINAL PROBABILITY CAP
    # ------------------------------------------------------

    # V2 deliberately refuses extreme confidence.
    p_more = max(
        0.27,
        min(
            0.73,
            p_more,
        ),
    )

    p_less = (
        1.0
        - p_more
    )

    # ------------------------------------------------------
    # PREDICTIVE INTERVAL
    # ------------------------------------------------------

    interval_z = 1.2816

    interval_low = (
        projection
        - interval_z
        * sigma
    )

    interval_high = (
        projection
        + interval_z
        * sigma
    )

    # ------------------------------------------------------
    # CONFIDENCE
    # ------------------------------------------------------

    edge = max(
        p_more,
        p_less,
    )

    if edge < 0.58:

        lean = "PASS"
        confidence = "LOW"

    elif edge < 0.67:

        lean = (
            "MORE"
            if p_more > p_less
            else "LESS"
        )

        confidence = "MODERATE"

    else:

        lean = (
            "MORE"
            if p_more > p_less
            else "LESS"
        )

        confidence = "HIGH"

    # HIGH requires stronger structural agreement.
    #
    # A probability alone is no longer enough.
    if (
        confidence == "HIGH"
        and (
            agreement_count < 3
            or model_disagreement
            or role_unstable
        )
    ):

        confidence = "MODERATE"

    return {
        "projection": projection,
        "sigma": sigma,

        "p_more": p_more,
        "p_less": p_less,

        "interval_low": interval_low,
        "interval_high": interval_high,

        "lean": lean,
        "confidence": confidence,

        "sample_size": n,

        "season_avg": season_avg,
        "l20_avg": l20_avg,
        "l10_avg": l10_avg,
        "l5_avg": l5_avg,

        "season_more_rate": season_more,
        "l20_more_rate": l20_more,
        "l10_more_rate": l10_more,
        "l5_more_rate": l5_more,

        "empirical_more_rate": empirical_more,

        "window_agreement": agreement_count,
        "model_disagreement": model_disagreement,
        "role_unstable": role_unstable,

        "projection_before_h2h": projection_before_h2h,

        "h2h_games": len(
            h2h_values
        ),

        "spread": spread,

        "blowout_level": blowout_level,
        "blowout_multiplier": blowout_multiplier,

        "projection_before_blowout": projection_before_blowout,

        "projection_before_minutes": projection_before_minutes,

        # Preserve old key so Flask/template remains compatible.
        "minutes_multiplier": role_minutes_multiplier,

        "minutes_context": minutes_context,

        "projection_before_matchup": projection_before_matchup,

        "matchup_multiplier": matchup_multiplier,
        "matchup_label": matchup_label,
        "matchup_profile": matchup_profile_data,
    }


def display_prediction_v1(
    games,
    prop,
    line,
    opponent=None,
    spread=None
):

    prediction = predict_prop_v1(
        games,
        prop,
        line,
        opponent,
        spread
    )

    print()
    print("=" * 55)
    print("MODEL PREDICTION — V1 + BLOWOUT RISK")
    print("=" * 55)

    if prediction is None:

        print(
            "Not enough historical data to create a prediction."
        )

        return

    print(
        "Player:",
        games[0]["player"]
    )

    if opponent:
        print(
            "Opponent:",
            opponent.upper()
        )

    print(
        "Prop:",
        prop.upper()
    )

    print(
        "Line:",
        line
    )

    if spread is not None:
        print(
            "Team spread:",
            f"{spread:+.1f}"
        )
        print(
            "Blowout risk:",
            prediction["blowout_level"]
        )
        print(
            "Projection before blowout adjustment:",
            f"{prediction['projection_before_blowout']:.2f}"
        )

    print()
    print(
        "Projection:",
        f"{prediction['projection']:.2f}"
    )

    print(
        "80% predictive range:",
        f"{prediction['interval_low']:.2f}",
        "to",
        f"{prediction['interval_high']:.2f}"
    )

    print(
        "Observed volatility:",
        f"{prediction['sigma']:.2f}"
    )

    print()
    print(
        "P(MORE):",
        f"{prediction['p_more'] * 100:.1f}%"
    )

    print(
        "P(LESS):",
        f"{prediction['p_less'] * 100:.1f}%"
    )

    print()
    print(
        "MODEL LEAN:",
        prediction["lean"]
    )

    print(
        "CONFIDENCE:",
        prediction["confidence"]
    )

    print()
    print(
        "NOTE: V1 probabilities are model estimates, not yet "
        "fully calibrated against historical market-line snapshots."
    )

    print(
        "Current injury information is displayed separately and "
        "is not yet used as a numerical adjustment in V1."
    )



# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":

    if len(sys.argv) < 2:

        print()
        print(
            'Usage: python3 main.py '
            '"Player Name" [prop] [line] [opponent] [team_spread]'
        )

        print()
        print("Examples:")

        print(
            'python3 main.py '
            '"A\'ja Wilson"'
        )

        print(
            'python3 main.py '
            '"A\'ja Wilson" rebounds 10.5'
        )

        print(
            'python3 main.py '
            '"A\'ja Wilson" rebounds 10.5 PHX'
        )

        print(
            'python3 main.py '
            '"A\'ja Wilson" rebounds 10.5 PHX -12.5'
        )

        sys.exit()

    player_name = sys.argv[1]

    games = get_player_games(
        player_name,
        season=CURRENT_SEASON
    )

    if not games:

        print()
        print(
            f"No games found for "
            f"'{player_name}' in {CURRENT_SEASON}"
        )

        sys.exit()

    # ------------------------------------------------------
    # PLAYER REPORT ONLY
    # ------------------------------------------------------

    if len(sys.argv) == 2:

        analyze_player(
            player_name,
            season=CURRENT_SEASON
        )

    # ------------------------------------------------------
    # PROP ANALYSIS
    # ------------------------------------------------------

    elif len(sys.argv) >= 4:

        prop = sys.argv[2].lower()

        valid_props = {
            "points",
            "rebounds",
            "assists",
            "3pm",
            "pra",
            "ra",
            "pa",
            "pr",
            "minutes"
        }

        if prop not in valid_props:

            print()
            print(
                f"Unknown prop: {prop}"
            )

            print(
                "Valid props:",
                ", ".join(
                    sorted(valid_props)
                )
            )

            sys.exit()

        try:

            line = float(
                sys.argv[3]
            )

        except ValueError:

            print(
                "Prop line must be a number."
            )

            sys.exit()

        opponent = None

        if len(sys.argv) >= 5:

            opponent = (
                sys.argv[4]
                .strip()
                .upper()
            )

        spread = None

        if len(sys.argv) >= 6:
            try:
                spread = float(sys.argv[5])
            except ValueError:
                print("Team spread must be a number, for example -12.5 or +8.5.")
                sys.exit()

        print()
        print(
            games[0]["player"].upper()
        )

        # 1. PROP HISTORY
        analyze_line(
            games,
            prop,
            line
        )

        # 2. MINUTES / ROLE / OPPORTUNITY
        analyze_opportunity(
            games
        )

        # 3. HOME / AWAY / REST
        analyze_context(
            games,
            prop,
            line,
            opponent
        )

        # 4. V2 EXPECTED MINUTES + OPPONENT PROFILE
        display_v2_context(
            games,
            games[0]["player"],
            prop,
            opponent
        )

        # 5. CURRENT INJURIES / AVAILABILITY
        analyze_injuries(
            games,
            games[0]["player"],
            opponent
        )

        # 5. CURRENT-SEASON MATCHUP
        if opponent:

            analyze_matchup(
                games,
                prop,
                line,
                opponent
            )

        # 6. MODEL PREDICTION V1
        display_prediction_v1(
            games,
            prop,
            line,
            opponent,
            spread
        )

    else:

        print()
        print(
            "Please provide both a prop and line."
        )