"""
MLB engine for Sports Prop AI.

Uses MLB's public Stats API at runtime for player lookup/game logs.
The model is intentionally separate from the WNBA engine.

Important:
- This is a pregame projection model, not a guarantee.
- Lineups/weather/injuries are surfaced as context hooks but should only be
  numerically adjusted when reliable pregame data is available.
"""

import math
import statistics
import urllib.parse
import urllib.request
import json
from datetime import datetime


MLB_API = "https://statsapi.mlb.com/api"


HITTER_PROPS = [
    "hits",
    "total_bases",
    "runs",
    "rbi",
    "walks",
    "home_runs",
    "hitter_fantasy_score",
]


PITCHER_PROPS = [
    "strikeouts",
    "pitching_outs",
    "hits_allowed",
    "walks_allowed",
    "earned_runs",
    "pitcher_fantasy_score",
]


# ============================================================
# MLB API
# ============================================================

def _json(url, timeout=12):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "SportsPropAI/1.0"},
    )

    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def find_player(name):
    q = urllib.parse.quote(name)

    data = _json(
        f"{MLB_API}/v1/people/search"
        f"?names={q}&sportIds=1"
    )

    people = data.get("people", [])

    if not people:
        return None

    exact = [
        p for p in people
        if p.get("fullName", "").lower() == name.lower()
    ]

    return (exact or people)[0]


def player_game_log(player_id, season, group):
    hydrate = urllib.parse.quote("team")

    url = (
        f"{MLB_API}/v1/people/{player_id}/stats"
        f"?stats=gameLog"
        f"&group={group}"
        f"&season={season}"
        f"&hydrate={hydrate}"
    )

    data = _json(url)

    stats = data.get("stats", [])

    if not stats:
        return []

    splits = stats[0].get("splits", [])

    games = []

    for s in splits:
        stat = s.get("stat", {})
        game = s.get("game", {})
        opp = s.get("opponent", {})
        team = s.get("team", {})

        games.append(
            {
                "date": s.get("date"),
                "game_pk": game.get("gamePk"),
                "opponent": opp.get("name"),
                "opponent_id": opp.get("id"),
                "team": team.get("name"),
                "stat": stat,
                "is_home": s.get("isHome"),
            }
        )

    games.sort(key=lambda x: x.get("date") or "")

    return games


# ============================================================
# BASIC HELPERS
# ============================================================

def _num(v, default=0.0):
    try:
        return float(v)

    except (TypeError, ValueError):
        return default


# ============================================================
# PROP VALUES
# ============================================================

def hitter_value(game, prop):
    s = game["stat"]

    hits = _num(s.get("hits"))
    doubles = _num(s.get("doubles"))
    triples = _num(s.get("triples"))
    hr = _num(s.get("homeRuns"))

    singles = max(
        0.0,
        hits - doubles - triples - hr,
    )

    tb = (
        singles
        + 2 * doubles
        + 3 * triples
        + 4 * hr
    )

    vals = {
        "hits": hits,

        "total_bases": _num(
            s.get("totalBases"),
            tb,
        ),

        "runs": _num(s.get("runs")),

        "rbi": _num(s.get("rbi")),

        "walks": _num(
            s.get("baseOnBalls")
        ),

        "home_runs": hr,

        # PrizePicks-style common scoring approximation.
        "hitter_fantasy_score": (
            3 * singles
            + 6 * doubles
            + 9 * triples
            + 12 * hr
            + 3 * _num(s.get("baseOnBalls"))
            + 3 * _num(s.get("hitByPitch"))
            + 3 * _num(s.get("stolenBases"))
            + 3 * _num(s.get("runs"))
            + 3 * _num(s.get("rbi"))
        ),
    }

    return vals[prop]


def pitcher_value(game, prop):
    s = game["stat"]

    ip = str(
        s.get(
            "inningsPitched",
            "0.0",
        )
    )

    try:
        whole, frac = ip.split(".")

        outs = (
            int(whole) * 3
            + int(frac)
        )

    except Exception:
        outs = int(
            _num(ip) * 3
        )

    vals = {
        "strikeouts": _num(
            s.get("strikeOuts")
        ),

        "pitching_outs": float(outs),

        "hits_allowed": _num(
            s.get("hits")
        ),

        "walks_allowed": _num(
            s.get("baseOnBalls")
        ),

        "earned_runs": _num(
            s.get("earnedRuns")
        ),

        "pitcher_fantasy_score": (
            3 * outs
            + 3 * _num(s.get("strikeOuts"))
            - 3 * _num(s.get("earnedRuns"))
            - _num(s.get("hits"))
            - _num(s.get("baseOnBalls"))
            + 6 * _num(s.get("wins"))
        ),
    }

    return vals[prop]


# ============================================================
# WEIGHTED MEAN
# ============================================================

def weighted_mean(values, decay=0.94):
    if not values:
        return 0.0

    weights = [
        decay ** (len(values) - 1 - i)
        for i in range(len(values))
    ]

    return (
        sum(
            v * w
            for v, w in zip(values, weights)
        )
        / sum(weights)
    )


# ============================================================
# POISSON
# ============================================================

def poisson_cdf(k, lam):
    if lam <= 0:
        return 1.0

    term = math.exp(-lam)
    total = term

    for i in range(1, k + 1):
        term *= lam / i
        total += term

    return min(
        1.0,
        total,
    )


def count_prob_more(line, lam):
    """
    Poisson component for discrete count props.

    This is NOT used as the sole probability model anymore.
    """

    k = math.floor(line)

    return max(
        0.0,
        min(
            1.0,
            1.0 - poisson_cdf(
                k,
                max(lam, 0.01),
            ),
        ),
    )


# ============================================================
# NEW PROBABILITY MODEL
# ============================================================

def empirical_more_rate(values, line):
    """
    Actual percentage of historical games
    that finished above the selected line.
    """

    if not values:
        return 0.5

    overs = sum(
        1
        for value in values
        if value > line
    )

    return overs / len(values)


def normal_prob_more(line, mean, sigma):
    """
    Normal approximation used for composite
    fantasy-score type props.

    Unlike Poisson, this uses the player's
    actual observed volatility.
    """

    if sigma <= 0.01:
        if mean > line:
            return 0.99

        if mean < line:
            return 0.01

        return 0.50

    z = (
        (line - mean)
        / sigma
    )

    cdf = (
        0.5
        * (
            1.0
            + math.erf(
                z
                / math.sqrt(2.0)
            )
        )
    )

    return max(
        0.01,
        min(
            0.99,
            1.0 - cdf,
        ),
    )


def mlb_prop_probability(
    prop,
    line,
    projection,
    values,
):
    """
    Conservative, distribution-aware MLB probability calibration.

    Uses historical line-clearing rates, observed volatility,
    projection evidence, sample-size shrinkage, disagreement
    penalties, and conservative probability caps.
    """

    if not values:
        return 0.50

    prop = str(prop).lower()
    line = float(line)
    projection = float(projection)

    clean = []
    for value in values:
        try:
            clean.append(float(value))
        except (TypeError, ValueError):
            pass

    if not clean:
        return 0.50

    recent20 = clean[-20:]
    recent10 = clean[-10:]
    recent5 = clean[-5:]

    season_rate = empirical_more_rate(clean, line)
    l20_rate = empirical_more_rate(recent20, line)
    l10_rate = empirical_more_rate(recent10, line)
    l5_rate = empirical_more_rate(recent5, line)

    # L5 is deliberately small so a short streak cannot dominate.
    empirical = (
        0.45 * season_rate
        + 0.30 * l20_rate
        + 0.20 * l10_rate
        + 0.05 * l5_rate
    )

    volatility_sample = recent20 if len(recent20) >= 10 else clean

    if len(volatility_sample) >= 2:
        sigma = statistics.stdev(volatility_sample)
    else:
        sigma = 0.0

    # Conservative volatility floors by prop type.
    sigma_floors = {
        "hits": 0.75,
        "total_bases": 1.60,
        "runs": 0.65,
        "rbi": 0.80,
        "walks": 0.55,
        "home_runs": 0.35,
        "hitter_fantasy_score": 7.50,
        "strikeouts": 2.00,
        "pitching_outs": 3.25,
        "hits_allowed": 1.75,
        "walks_allowed": 1.25,
        "earned_runs": 1.75,
        "pitcher_fantasy_score": 10.00,
    }

    sigma = max(
        sigma,
        sigma_floors.get(
            prop,
            max(abs(projection) * 0.30, 1.0),
        ),
    )

    distribution_prob = normal_prob_more(
        line,
        projection,
        sigma,
    )

    fantasy_props = {
        "hitter_fantasy_score",
        "pitcher_fantasy_score",
    }

    if prop in fantasy_props:
        # Fantasy score is volatile: actual game outcomes dominate.
        raw_prob = (
            0.75 * empirical
            + 0.25 * distribution_prob
        )
    else:
        poisson_prob = count_prob_more(
            line,
            max(projection, 0.01),
        )

        raw_prob = (
            0.65 * empirical
            + 0.20 * distribution_prob
            + 0.15 * poisson_prob
        )

    # Shrink toward 50%; even a full season is not perfect information.
    sample_size = len(clean)
    reliability = min(
        0.88,
        sample_size / 70.0,
    )

    calibrated = (
        0.50
        + (raw_prob - 0.50) * reliability
    )

    # Penalize confidence when projection and empirical history disagree.
    if (distribution_prob >= 0.50) != (empirical >= 0.50):
        calibrated = (
            0.50
            + (calibrated - 0.50) * 0.70
        )

    # Prevent public-game-log models from advertising fake certainty.
    if prop in fantasy_props:
        lower_cap = 0.30
        upper_cap = 0.70
    else:
        lower_cap = 0.27
        upper_cap = 0.73

    return max(
        lower_cap,
        min(
            upper_cap,
            calibrated,
        ),
    )


# ============================================================
# RECENT FORM
# ============================================================

def recent_context(values):
    season = statistics.mean(
        values
    )

    l20 = statistics.mean(
        values[-20:]
    )

    l10 = statistics.mean(
        values[-10:]
    )

    l5 = statistics.mean(
        values[-5:]
    )

    # More balanced than the old:
    # 45% season / 25% L20 / 20% L10 / 10% L5.
    #
    # Long-term ability still matters,
    # but recent performance gets more influence.
    baseline = (
        0.30 * season
        + 0.30 * l20
        + 0.25 * l10
        + 0.15 * l5
    )

    return (
        season,
        l20,
        l10,
        l5,
        baseline,
    )


# ============================================================
# OPPONENT HISTORY
# ============================================================

def opponent_history(
    games,
    opponent,
    value_fn,
    prop,
):
    """
    Historical games against the opponent TEAM.

    This is not batter-vs-pitcher history.
    """

    if not opponent:
        return []

    o = opponent.lower()

    return [
        value_fn(g, prop)
        for g in games
        if o
        in str(
            g.get(
                "opponent",
                "",
            )
        ).lower()
    ]


# ============================================================
# MAIN MLB ANALYSIS
# ============================================================

def analyze_mlb(
    player_name,
    player_type,
    prop,
    line,
    opponent=None,
    season=None,
):

    if season is None:
        season = datetime.now().year

    player_type = player_type.lower()
    prop = prop.lower()

    allowed = (
        HITTER_PROPS
        if player_type == "hitter"
        else PITCHER_PROPS
    )

    if prop not in allowed:
        raise ValueError(
            f"{prop} is not valid "
            f"for {player_type}"
        )

    p = find_player(
        player_name
    )

    if not p:
        raise ValueError(
            "MLB player not found."
        )

    group = (
        "hitting"
        if player_type == "hitter"
        else "pitching"
    )

    games = player_game_log(
        p["id"],
        season,
        group,
    )

    value_fn = (
        hitter_value
        if player_type == "hitter"
        else pitcher_value
    )

    values = [
        value_fn(
            g,
            prop,
        )
        for g in games
    ]

    if len(values) < 10:
        raise ValueError(
            "Not enough MLB games "
            "in the selected season."
        )

    (
        season_avg,
        l20,
        l10,
        l5,
        projection,
    ) = recent_context(
        values
    )

    original = projection

    # --------------------------------------------------------
    # Opponent-team history
    # --------------------------------------------------------

    h2h = opponent_history(
        games,
        opponent,
        value_fn,
        prop,
    )

    h2h_adj = 0.0

    if len(h2h) >= 2:

        h2h_avg = statistics.mean(
            h2h
        )

        # Keep opponent history supporting,
        # never dominant.
        h2h_weight = min(
            0.12,
            0.03 * len(h2h),
        )

        projection = (
            (1 - h2h_weight)
            * projection
            + h2h_weight
            * h2h_avg
        )

        h2h_adj = (
            projection
            - original
        )

    # --------------------------------------------------------
    # Correct probability
    # --------------------------------------------------------

    p_more = mlb_prop_probability(
        prop,
        float(line),
        projection,
        values,
    )

    p_less = (
        1.0
        - p_more
    )

    best = max(
        p_more,
        p_less,
    )

    lean = (
        "MORE"
        if p_more > p_less
        else "LESS"
    )

    confidence = (
        "PASS"
        if best < 0.58
        else (
            "MODERATE"
            if best < 0.67
            else "HIGH"
        )
    )

    if confidence == "PASS":
        lean = "PASS"

    recent = (
        values[-20:]
        if len(values) >= 20
        else values
    )

    sigma = (
        statistics.stdev(recent)
        if len(recent) >= 2
        else 0.0
    )

    # --------------------------------------------------------
    # Hit rates for audit/display
    # --------------------------------------------------------

    season_more_rate = empirical_more_rate(
        values,
        float(line),
    )

    l20_more_rate = empirical_more_rate(
        values[-20:],
        float(line),
    )

    l10_more_rate = empirical_more_rate(
        values[-10:],
        float(line),
    )

    l5_more_rate = empirical_more_rate(
        values[-5:],
        float(line),
    )

    return {
        "player": p.get(
            "fullName",
            player_name,
        ),

        "player_id": p["id"],

        "player_type": (
            player_type.upper()
        ),

        "prop": prop.upper(),

        "line": float(line),

        "opponent": opponent,

        "projection": projection,

        "projection_before_h2h": original,

        "h2h_adjustment": h2h_adj,

        "p_more": p_more,

        "p_less": p_less,

        "lean": lean,

        "confidence": confidence,

        "season_avg": season_avg,

        "l20": l20,

        "l10": l10,

        "l5": l5,

        "sigma": sigma,

        "sample_size": len(values),

        "h2h_games": len(h2h),

        "h2h_avg": (
            statistics.mean(h2h)
            if h2h
            else None
        ),

        "season_more_rate": season_more_rate,

        "l20_more_rate": l20_more_rate,

        "l10_more_rate": l10_more_rate,

        "l5_more_rate": l5_more_rate,

        "last10": values[-10:],

        # Internal data needed when verified
        # pregame adjustment recomputes probability.
        "_values": values,

        "model_note": (
            "MLB model combines multi-horizon form, "
            "actual line-clearing rates, player volatility, "
            "small opponent-team history support, and verified "
            "pregame information. Fantasy scores do not use "
            "Poisson as a standalone probability model."
        ),
    }


# ============================================================
# MLB TEAMS
# ============================================================

def mlb_teams(season=None):

    if season is None:
        season = datetime.now().year

    data = _json(
        f"{MLB_API}/v1/teams"
        f"?sportId=1"
        f"&season={season}"
    )

    teams = []

    for t in data.get(
        "teams",
        [],
    ):

        teams.append(
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "abbreviation": t.get(
                    "abbreviation"
                ),
            }
        )

    return sorted(
        teams,
        key=lambda x: x["name"] or "",
    )


# ============================================================
# MLB ROSTER
# ============================================================

def mlb_team_roster(
    team_id,
    season=None,
):

    if season is None:
        season = datetime.now().year

    data = _json(
        f"{MLB_API}/v1/teams/"
        f"{int(team_id)}/roster"
        f"?rosterType=active"
        f"&season={season}"
    )

    players = []

    for item in data.get(
        "roster",
        [],
    ):

        person = item.get(
            "person",
            {},
        )

        pos = item.get(
            "position",
            {},
        )

        players.append(
            {
                "id": person.get("id"),
                "name": person.get(
                    "fullName"
                ),
                "position": pos.get(
                    "abbreviation"
                ),
                "position_type": pos.get(
                    "type"
                ),
            }
        )

    return sorted(
        players,
        key=lambda x: x["name"] or "",
    )


# ============================================================
# BASIC PREGAME GAME CONTEXT
# ============================================================

def mlb_pregame_game_context(
    team_id,
    opponent_id=None,
    date=None,
):

    if date is None:
        date = datetime.now().strftime(
            "%Y-%m-%d"
        )

    url = (
        f"{MLB_API}/v1/schedule"
        f"?sportId=1"
        f"&date={date}"
        f"&teamId={int(team_id)}"
        f"&hydrate=probablePitcher,team,linescore"
    )

    data = _json(url)

    games = []

    for d in data.get(
        "dates",
        [],
    ):

        for g in d.get(
            "games",
            [],
        ):

            away = (
                g.get(
                    "teams",
                    {},
                )
                .get(
                    "away",
                    {},
                )
            )

            home = (
                g.get(
                    "teams",
                    {},
                )
                .get(
                    "home",
                    {},
                )
            )

            away_id = (
                away.get(
                    "team",
                    {},
                )
                .get("id")
            )

            home_id = (
                home.get(
                    "team",
                    {},
                )
                .get("id")
            )

            if opponent_id:

                if int(opponent_id) not in (
                    away_id,
                    home_id,
                ):
                    continue

            games.append(
                {
                    "game_pk": g.get(
                        "gamePk"
                    ),

                    "status": (
                        g.get(
                            "status",
                            {},
                        )
                        .get(
                            "detailedState"
                        )
                    ),

                    "away": (
                        away.get(
                            "team",
                            {},
                        )
                        .get("name")
                    ),

                    "home": (
                        home.get(
                            "team",
                            {},
                        )
                        .get("name")
                    ),

                    "away_probable": (
                        away.get(
                            "probablePitcher"
                        )
                        or {}
                    ).get(
                        "fullName"
                    ),

                    "home_probable": (
                        home.get(
                            "probablePitcher"
                        )
                        or {}
                    ).get(
                        "fullName"
                    ),
                }
            )

    return games


# ============================================================
# VERIFIED PREGAME CONTEXT
# ============================================================

def _person_details(person_id):

    try:

        d = _json(
            f"{MLB_API}/v1/people/"
            f"{int(person_id)}"
        )

        p = (
            d.get("people")
            or [{}]
        )[0]

        return {
            "id": p.get("id"),

            "name": p.get(
                "fullName"
            ),

            "bat_side": (
                p.get("batSide")
                or {}
            ).get("code"),

            "pitch_hand": (
                p.get("pitchHand")
                or {}
            ).get("code"),
        }

    except Exception:
        return {}


def _live_feed(game_pk):

    return _json(
        f"{MLB_API}/v1.1/game/"
        f"{int(game_pk)}/feed/live"
    )


def _weather_from_feed(feed):

    gd = feed.get(
        "gameData",
        {},
    )

    w = (
        gd.get("weather")
        or {}
    )

    venue = (
        gd.get("venue")
        or {}
    )

    return {
        "venue": venue.get("name"),

        "condition": w.get(
            "condition"
        ),

        "temp_f": w.get(
            "temp"
        ),

        "wind": w.get(
            "wind"
        ),
    }


def _confirmed_lineups(feed):
    """
    Only returns batting order when MLB
    live-feed contains an actual battingOrder.

    Empty battingOrder = unavailable.
    We never infer or guess.
    """

    box = (
        feed.get(
            "liveData"
        )
        or {}
    ).get(
        "boxscore"
    ) or {}

    teams = (
        box.get("teams")
        or {}
    )

    result = {}

    for side in (
        "away",
        "home",
    ):

        td = (
            teams.get(side)
            or {}
        )

        order = (
            td.get(
                "battingOrder"
            )
            or []
        )

        players = (
            td.get(
                "players"
            )
            or {}
        )

        lineup = []

        for i, pid in enumerate(
            order,
            start=1,
        ):

            pd = players.get(
                f"ID{pid}",
                {},
            )

            person = (
                pd.get("person")
                or {}
            )

            lineup.append(
                {
                    "order": i,

                    "id": pid,

                    "name": person.get(
                        "fullName"
                    ),

                    "position": (
                        pd.get(
                            "position"
                        )
                        or {}
                    ).get(
                        "abbreviation"
                    ),
                }
            )

        result[side] = lineup

    return result


def _find_today_game(
    team_id,
    opponent_id=None,
    date=None,
):

    games = mlb_pregame_game_context(
        team_id,
        opponent_id,
        date,
    )

    return (
        games[0]
        if games
        else None
    )


def _schedule_game_full(
    team_id,
    opponent_id=None,
    date=None,
):

    if date is None:
        date = datetime.now().strftime(
            "%Y-%m-%d"
        )

    url = (
        f"{MLB_API}/v1/schedule"
        f"?sportId=1"
        f"&date={date}"
        f"&teamId={int(team_id)}"
        f"&hydrate=probablePitcher,team,venue"
    )

    data = _json(url)

    for d in data.get(
        "dates",
        [],
    ):

        for g in d.get(
            "games",
            [],
        ):

            away = (
                g.get(
                    "teams",
                    {},
                )
                .get(
                    "away",
                    {},
                )
            )

            home = (
                g.get(
                    "teams",
                    {},
                )
                .get(
                    "home",
                    {},
                )
            )

            aid = (
                away.get(
                    "team",
                    {},
                )
                .get("id")
            )

            hid = (
                home.get(
                    "team",
                    {},
                )
                .get("id")
            )

            if opponent_id:

                if int(opponent_id) not in (
                    aid,
                    hid,
                ):
                    continue

            return {
                "game_pk": g.get(
                    "gamePk"
                ),

                "away_id": aid,

                "home_id": hid,

                "away": (
                    away.get(
                        "team",
                        {},
                    )
                    .get("name")
                ),

                "home": (
                    home.get(
                        "team",
                        {},
                    )
                    .get("name")
                ),

                "away_probable": (
                    away.get(
                        "probablePitcher"
                    )
                ),

                "home_probable": (
                    home.get(
                        "probablePitcher"
                    )
                ),

                "venue": (
                    g.get("venue")
                    or {}
                ).get(
                    "name"
                ),

                "status": (
                    g.get("status")
                    or {}
                ).get(
                    "detailedState"
                ),
            }

    return None


# ============================================================
# EXPECTED OPPORTUNITY
# ============================================================

def _recent_plate_appearances(
    games,
):

    vals = []

    for g in games[-20:]:

        s = g["stat"]

        pa = s.get(
            "plateAppearances"
        )

        if pa is None:

            pa = (
                _num(
                    s.get("atBats")
                )
                + _num(
                    s.get(
                        "baseOnBalls"
                    )
                )
                + _num(
                    s.get(
                        "hitByPitch"
                    )
                )
                + _num(
                    s.get(
                        "sacFlies"
                    )
                )
                + _num(
                    s.get(
                        "sacBunts"
                    )
                )
            )

        vals.append(
            _num(pa)
        )

    return (
        weighted_mean(vals)
        if vals
        else None
    )


def _recent_pitcher_outs(
    games,
):

    vals = []

    for g in games[-10:]:

        vals.append(
            pitcher_value(
                g,
                "pitching_outs",
            )
        )

    return (
        weighted_mean(vals)
        if vals
        else None
    )


def _lineup_pa_multiplier(slot):
    """
    Conservative opportunity-only adjustment
    after lineup is confirmed.
    """

    return {
        1: 1.06,
        2: 1.045,
        3: 1.025,
        4: 1.01,
        5: 1.00,
        6: 0.98,
        7: 0.96,
        8: 0.94,
        9: 0.92,
    }.get(
        slot,
        1.0,
    )


# ============================================================
# VERIFIED PREGAME
# ============================================================


# ============================================================
# VERIFIED STARTING-PITCHER QUALITY
# ============================================================

def _pitcher_season_quality(person_id, season):
    """
    Fetch verified MLB pitching quality.

    Priority:
    1. Established current-season sample.
    2. Blend current + previous season for small samples.
    3. Previous-season fallback if current data is unavailable.
    4. Conservative current-season data for pitchers with
       limited MLB history.

    Missing statistics are never invented.
    """

    def fetch(target_season):

        try:
            url = (
                f"{MLB_API}/v1/people/{int(person_id)}/stats"
                f"?stats=season"
                f"&group=pitching"
                f"&season={int(target_season)}"
            )

            data = _json(url)

            splits = []

            for block in data.get("stats", []):
                splits.extend(
                    block.get("splits", [])
                )

            if not splits:
                return None

            stat = (
                splits[0].get("stat", {})
                or {}
            )

            def number(key):

                value = stat.get(key)

                if value in (
                    None,
                    "",
                    "-",
                    ".---",
                ):
                    return None

                try:
                    return float(value)

                except (
                    TypeError,
                    ValueError,
                ):
                    return None

            innings = stat.get(
                "inningsPitched"
            )

            try:
                innings = float(innings)

            except (
                TypeError,
                ValueError,
            ):
                innings = None

            result = {
                "era": number("era"),
                "whip": number("whip"),
                "k9": number(
                    "strikeoutsPer9Inn"
                ),
                "bb9": number(
                    "walksPer9Inn"
                ),
                "h9": number(
                    "hitsPer9Inn"
                ),
                "hr9": number(
                    "homeRunsPer9"
                ),
                "innings": innings,
                "season": int(
                    target_season
                ),
            }

            useful = [
                result["era"],
                result["whip"],
                result["k9"],
                result["h9"],
            ]

            if all(
                value is None
                for value in useful
            ):
                return None

            return result

        except Exception:
            return None

    current = fetch(season)

    previous = fetch(
        int(season) - 1
    )

    # No current-season MLB data.
    if current is None:

        if previous is None:
            return None

        previous[
            "data_source"
        ] = "PRIOR SEASON"

        previous[
            "sample_reliability"
        ] = 0.65

        return previous

    current_ip = float(
        current.get("innings")
        or 0.0
    )

    # Established current-season sample.
    if current_ip >= 40:

        current[
            "data_source"
        ] = "CURRENT SEASON"

        current[
            "sample_reliability"
        ] = min(
            1.0,
            max(
                0.55,
                current_ip / 100.0,
            ),
        )

        return current

    # Small current sample + previous MLB season.
    if previous is not None:

        previous_ip = float(
            previous.get("innings")
            or 0.0
        )

        current_weight = min(
            0.70,
            max(
                0.25,
                current_ip / 40.0,
            ),
        )

        if previous_ip < 20:
            current_weight = max(
                current_weight,
                0.60,
            )

        prior_weight = (
            1.0 - current_weight
        )

        blended = {}

        for key in (
            "era",
            "whip",
            "k9",
            "bb9",
            "h9",
            "hr9",
        ):

            c = current.get(key)
            p = previous.get(key)

            if (
                c is not None
                and p is not None
            ):
                blended[key] = (
                    current_weight * c
                    + prior_weight * p
                )

            elif c is not None:
                blended[key] = c

            else:
                blended[key] = p

        blended[
            "innings"
        ] = current_ip

        blended[
            "season"
        ] = int(season)

        blended[
            "current_innings"
        ] = current_ip

        blended[
            "prior_innings"
        ] = previous_ip

        blended[
            "data_source"
        ] = "CURRENT + PRIOR BLEND"

        blended[
            "sample_reliability"
        ] = min(
            0.85,
            max(
                0.40,
                (
                    current_ip
                    + (
                        min(
                            previous_ip,
                            80.0,
                        )
                        * 0.50
                    )
                )
                / 80.0,
            ),
        )

        return blended

    # Rookie / spot starter / limited MLB history.
    current[
        "data_source"
    ] = "LIMITED CURRENT SEASON"

    current[
        "sample_reliability"
    ] = min(
        0.60,
        max(
            0.20,
            current_ip / 40.0,
        ),
    )

    return current


def _starter_matchup_multiplier(stats):
    """
    Convert verified starter quality into a conservative
    hitter projection multiplier.

    < 1.00 = difficult pitcher matchup
    > 1.00 = favorable pitcher matchup

    The adjustment is deliberately capped. Starting-pitcher
    quality should matter, but should never completely replace
    the hitter's own historical production.
    """

    if not stats:
        return 1.0, "unavailable", 0.0

    # Approximate neutral MLB run-environment reference points.
    # These are anchors, not claims about the exact league
    # average for every season.
    neutral = {
        "era": 4.20,
        "whip": 1.30,
        "k9": 8.50,
        "bb9": 3.20,
        "h9": 8.50,
        "hr9": 1.15,
    }

    score = 0.0
    used = 0.0

    # Lower ERA is harder for a hitter.
    if stats.get("era") is not None:
        score += (
            (stats["era"] - neutral["era"]) / 1.50
        ) * 0.30
        used += 0.30

    # Lower WHIP is harder for a hitter.
    if stats.get("whip") is not None:
        score += (
            (stats["whip"] - neutral["whip"]) / 0.30
        ) * 0.25
        used += 0.25

    # Higher K/9 is harder for a hitter.
    if stats.get("k9") is not None:
        score += (
            (neutral["k9"] - stats["k9"]) / 3.00
        ) * 0.20
        used += 0.20

    # Lower H/9 is harder for a hitter.
    if stats.get("h9") is not None:
        score += (
            (stats["h9"] - neutral["h9"]) / 2.00
        ) * 0.12
        used += 0.12

    # Lower HR/9 is harder for fantasy-score upside.
    if stats.get("hr9") is not None:
        score += (
            (stats["hr9"] - neutral["hr9"]) / 0.70
        ) * 0.08
        used += 0.08

    # Lower BB/9 slightly reduces free-base opportunities.
    if stats.get("bb9") is not None:
        score += (
            (stats["bb9"] - neutral["bb9"]) / 1.50
        ) * 0.05
        used += 0.05

    if used <= 0:
        return 1.0, "unavailable", 0.0

    score /= used

    # --------------------------------------------------------
    # Sample-size reliability
    # --------------------------------------------------------

    innings = stats.get("innings")

    explicit_reliability = stats.get(
        "sample_reliability"
    )

    if explicit_reliability is not None:

        reliability = max(
            0.20,
            min(
                1.0,
                float(
                    explicit_reliability
                ),
            ),
        )

    elif innings is None:

        reliability = 0.60

    else:

        reliability = min(
            1.0,
            max(
                0.35,
                innings / 80.0,
            ),
        )

    score *= reliability

    # Convert quality score into a conservative multiplier.
    #
    # Strong pitcher:
    # score negative -> hitter projection reduced.
    #
    # Weak pitcher:
    # score positive -> hitter projection increased.
    #
    raw_multiplier = 1.0 + (0.085 * score)

    multiplier = max(
        0.88,
        min(
            1.12,
            raw_multiplier,
        ),
    )

    if multiplier <= 0.94:
        label = "VERY DIFFICULT"
    elif multiplier <= 0.975:
        label = "DIFFICULT"
    elif multiplier < 1.025:
        label = "NEUTRAL"
    elif multiplier < 1.06:
        label = "FAVORABLE"
    else:
        label = "VERY FAVORABLE"

    return multiplier, label, score


def _matchup_confidence_shrink(
    base_projection,
    adjusted_projection,
    line,
    p_more,
):
    """
    Reduce certainty when hitter form and today's verified
    pitcher matchup disagree.

    This NEVER flips a probability by itself. It pulls an
    overconfident probability toward 50%.
    """

    try:
        base_projection = float(base_projection)
        adjusted_projection = float(adjusted_projection)
        line = float(line)
        p_more = float(p_more)
    except (TypeError, ValueError):
        return p_more

    before_side = (
        1 if base_projection > line
        else -1 if base_projection < line
        else 0
    )

    after_side = (
        1 if adjusted_projection > line
        else -1 if adjusted_projection < line
        else 0
    )

    # If matchup actually moves the projection across the line,
    # disagreement is substantial.
    if (
        before_side != 0
        and after_side != 0
        and before_side != after_side
    ):
        shrink = 0.68

    else:
        if base_projection == 0:
            change = 0.0
        else:
            change = abs(
                adjusted_projection - base_projection
            ) / abs(base_projection)

        if change >= 0.08:
            shrink = 0.78
        elif change >= 0.04:
            shrink = 0.88
        else:
            shrink = 1.0

    return 0.50 + (
        (p_more - 0.50)
        * shrink
    )


def verified_pregame_context(
    player_name,
    player_type,
    team_id,
    opponent_id,
    season=None,
):
    """
    Missing verified data is marked unavailable
    and produces NO adjustment.

    Never guesses:
    - batting slot
    - starter
    - handedness
    - weather
    - injury status
    """

    if season is None:
        season = datetime.now().year

    game = _schedule_game_full(
        team_id,
        opponent_id,
    )

    status = {
        "game": (
            "available"
            if game
            else "unavailable"
        ),

        "lineup": "unavailable",

        "in_starting_lineup": None,

        "batting_order": None,

        "opposing_starter": "unavailable",

        "starter_name": None,

        "starter_hand": None,

        "starter_stats": None,

        "starter_matchup": "unavailable",

        "starter_multiplier": 1.0,

        "player_hand": None,

        "handedness_split": "unavailable",

        "expected_opportunity": "unavailable",

        "expected_pa": None,

        "expected_outs": None,

        "park": "unavailable",

        "venue": None,

        "weather": "unavailable",

        "weather_text": None,

        "injuries": "unavailable",

        "notes": [],

        "projection_multiplier": 1.0,
    }

    if not game:

        status["notes"].append(
            "No matching MLB game found today. "
            "No pregame adjustment applied."
        )

        return status

    status["venue"] = game.get(
        "venue"
    )

    status["park"] = (
        "available"
        if status["venue"]
        else "unavailable"
    )

    # --------------------------------------------------------
    # LIVE FEED
    # --------------------------------------------------------

    try:

        feed = _live_feed(
            game["game_pk"]
        )

    except Exception:

        feed = None

    if feed:

        weather = _weather_from_feed(
            feed
        )

        if (
            weather.get("condition")
            or weather.get("temp_f")
            or weather.get("wind")
        ):

            status["weather"] = (
                "available"
            )

            bits = [
                str(x)
                for x in [
                    weather.get(
                        "condition"
                    ),

                    (
                        f'{weather.get("temp_f")}F'
                        if weather.get(
                            "temp_f"
                        )
                        else None
                    ),

                    weather.get(
                        "wind"
                    ),
                ]
                if x
            ]

            status["weather_text"] = (
                " · ".join(bits)
            )

        lineups = _confirmed_lineups(
            feed
        )

        player_side = (
            "home"
            if int(team_id)
            == game["home_id"]
            else "away"
        )

        lineup = (
            lineups.get(
                player_side
            )
            or []
        )

        if lineup:

            status["lineup"] = (
                "confirmed"
            )

            hit = next(
                (
                    x
                    for x in lineup
                    if (
                        x.get("name")
                        or ""
                    ).lower()
                    == player_name.lower()
                ),
                None,
            )

            if hit:

                status[
                    "in_starting_lineup"
                ] = True

                status[
                    "batting_order"
                ] = hit["order"]

                status[
                    "projection_multiplier"
                ] *= _lineup_pa_multiplier(
                    hit["order"]
                )

            else:

                status[
                    "in_starting_lineup"
                ] = False

                status["notes"].append(
                    "Team lineup is posted, "
                    "but selected player is not "
                    "in the confirmed batting order."
                )

        else:

            status["notes"].append(
                "Confirmed batting order is not posted. "
                "Lineup adjustment NOT applied."
            )

    # --------------------------------------------------------
    # OPPOSING STARTER
    # --------------------------------------------------------

    player_side = (
        "home"
        if int(team_id)
        == game["home_id"]
        else "away"
    )

    opp_prob = (
        game["away_probable"]
        if player_side == "home"
        else game["home_probable"]
    )

    if (
        opp_prob
        and opp_prob.get("id")
    ):

        status[
            "opposing_starter"
        ] = "available"

        status[
            "starter_name"
        ] = opp_prob.get(
            "fullName"
        )

        pd = _person_details(
            opp_prob["id"]
        )

        status[
            "starter_hand"
        ] = pd.get(
            "pitch_hand"
        )

        # ----------------------------------------------------
        # VERIFIED STARTER QUALITY
        # ----------------------------------------------------

        if player_type == "hitter":

            starter_stats = _pitcher_season_quality(
                opp_prob["id"],
                season,
            )

            status[
                "starter_stats"
            ] = starter_stats

            (
                starter_mult,
                starter_label,
                starter_score,
            ) = _starter_matchup_multiplier(
                starter_stats
            )

            status[
                "starter_multiplier"
            ] = starter_mult

            status[
                "starter_matchup"
            ] = starter_label

            status[
                "starter_quality_score"
            ] = starter_score

            status[
                "projection_multiplier"
            ] *= starter_mult

            if starter_stats:

                source = starter_stats.get(
                    "data_source",
                    "CURRENT SEASON",
                )

                status["notes"].append(
                    "Verified opposing starter quality "
                    f"applied: {starter_label} matchup "
                    f"(x{starter_mult:.3f}). "
                    f"Pitcher data: {source}."
                )

            else:

                status["notes"].append(
                    "Opposing starter identified, but "
                    "season pitching statistics were "
                    "unavailable. No pitcher-quality "
                    "adjustment applied."
                )

    # --------------------------------------------------------
    # PLAYER HAND
    # --------------------------------------------------------

    p = find_player(
        player_name
    )

    if p:

        pd = _person_details(
            p["id"]
        )

        status["player_hand"] = (
            pd.get("bat_side")
            if player_type == "hitter"
            else pd.get("pitch_hand")
        )

    # --------------------------------------------------------
    # HANDEDNESS
    # --------------------------------------------------------

    if (
        status["player_hand"]
        and status["starter_hand"]
    ):

        status[
            "handedness_split"
        ] = (
            "hands verified; "
            "split adjustment unavailable"
        )

        status["notes"].append(
            "Player/starter hands verified. "
            "No unverified handedness split "
            "multiplier applied."
        )

    # --------------------------------------------------------
    # EXPECTED OPPORTUNITY
    # --------------------------------------------------------

    group = (
        "hitting"
        if player_type == "hitter"
        else "pitching"
    )

    if p:

        games = player_game_log(
            p["id"],
            season,
            group,
        )

        if player_type == "hitter":

            status[
                "expected_pa"
            ] = _recent_plate_appearances(
                games
            )

            status[
                "expected_opportunity"
            ] = (
                "available"
                if status["expected_pa"]
                is not None
                else "unavailable"
            )

        else:

            status[
                "expected_outs"
            ] = _recent_pitcher_outs(
                games
            )

            status[
                "expected_opportunity"
            ] = (
                "available"
                if status["expected_outs"]
                is not None
                else "unavailable"
            )

    # --------------------------------------------------------
    # INJURY / WEATHER
    # --------------------------------------------------------

    status["notes"].append(
        "Injury adjustment: data unavailable, "
        "so no injury adjustment applied."
    )

    if status["weather"] == "unavailable":

        status["notes"].append(
            "Weather data unavailable, "
            "so no weather adjustment applied."
        )

    return status


# ============================================================
# VERIFIED ANALYSIS
# ============================================================

def analyze_mlb_verified(
    player_name,
    player_type,
    prop,
    line,
    team_id,
    opponent_id,
    opponent_name=None,
    season=None,
):

    result = analyze_mlb(
        player_name,
        player_type,
        prop,
        line,
        opponent_name,
        season,
    )

    pre = verified_pregame_context(
        player_name,
        player_type,
        team_id,
        opponent_id,
        season,
    )

    base = result[
        "projection"
    ]

    result[
        "projection_before_pregame"
    ] = base

    result["projection"] = (
        base
        * pre[
            "projection_multiplier"
        ]
    )

    # --------------------------------------------------------
    # IMPORTANT:
    # Recalculate probability using the NEW model,
    # NOT Poisson for everything.
    # --------------------------------------------------------

    values = result.get(
        "_values",
        [],
    )

    result[
        "p_more"
    ] = mlb_prop_probability(
        prop.lower(),
        float(line),
        result["projection"],
        values,
    )

    # --------------------------------------------------------
    # Matchup disagreement calibration
    # --------------------------------------------------------

    if (
        player_type.lower() == "hitter"
        and pre.get("starter_stats")
    ):

        result["p_more"] = (
            _matchup_confidence_shrink(
                base,
                result["projection"],
                float(line),
                result["p_more"],
            )
        )

    result[
        "p_less"
    ] = (
        1.0
        - result["p_more"]
    )

    best = max(
        result["p_more"],
        result["p_less"],
    )

    result["lean"] = (
        "MORE"
        if result["p_more"]
        > result["p_less"]
        else "LESS"
    )

    result["confidence"] = (
        "PASS"
        if best < 0.58
        else (
            "MODERATE"
            if best < 0.67
            else "HIGH"
        )
    )

    if (
        result["confidence"]
        == "PASS"
    ):

        result["lean"] = (
            "PASS"
        )

    # --------------------------------------------------------
    # CONFIRMED LINEUP SAFETY GATE
    # --------------------------------------------------------

    if (
        player_type.lower() == "hitter"
        and pre.get(
            "in_starting_lineup"
        ) is False
    ):

        result[
            "lean"
        ] = "PASS"

        result[
            "confidence"
        ] = "PASS"

        result[
            "lineup_warning"
        ] = (
            "NOT IN CONFIRMED STARTING LINEUP"
        )

    result["pregame"] = pre

    # Internal historical values are not needed
    # by Flask/templates after analysis.
    result.pop(
        "_values",
        None,
    )

    return result