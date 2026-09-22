import re
import unicodedata
from collections import defaultdict
from datetime import datetime

from propline_market import (
    MLB_MARKET_MAP,
    get_mlb_events,
    get_mlb_event_odds,
    find_mlb_event,
    build_market_consensus,
    compare_model_to_market,
)


# ============================================================
# CONFIG
# ============================================================

# Only props that have a verified PropLine market mapping.
SUPPORTED_MARKET_PROPS = set(MLB_MARKET_MAP.keys())


# ============================================================
# HELPERS
# ============================================================

def _normalize_text(value):
    if not value:
        return ""

    value = str(value).strip().lower()

    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )

    value = re.sub(r"[^a-z0-9\s]", "", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def _parse_time(value):
    if not value:
        return None

    try:
        value = str(value).strip()

        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        return datetime.fromisoformat(value)

    except (TypeError, ValueError):
        return None


def _extract_pp_teams(row):
    """
    Try to obtain away/home teams from a PrizePicks row.

    The bridge intentionally refuses to guess if the row
    does not contain enough game information.
    """

    away = (
        row.get("away_team")
        or row.get("away")
        or row.get("game_away_team")
    )

    home = (
        row.get("home_team")
        or row.get("home")
        or row.get("game_home_team")
    )

    if away and home:
        return str(away).strip(), str(home).strip()

    # Some rows may contain a matchup string.
    matchup = (
        row.get("matchup")
        or row.get("game")
        or row.get("game_name")
    )

    if matchup:
        matchup = str(matchup).strip()

        # Away @ Home
        if "@" in matchup:
            parts = matchup.split("@", 1)

            if len(parts) == 2:
                return (
                    parts[0].strip(),
                    parts[1].strip(),
                )

        # Away vs Home
        match = re.split(
            r"\s+vs\.?\s+",
            matchup,
            maxsplit=1,
            flags=re.IGNORECASE,
        )

        if len(match) == 2:
            return (
                match[0].strip(),
                match[1].strip(),
            )

    return None, None


def _pp_model_prop(row):
    """
    Return our internal MLB model prop name.

    prizepicks_board.py already provides 'model_prop'
    for supported rows in some versions, while other
    versions use 'prop'.
    """

    model_prop = row.get("model_prop")

    if model_prop in SUPPORTED_MARKET_PROPS:
        return model_prop

    prop = row.get("prop")

    if prop in SUPPORTED_MARKET_PROPS:
        return prop

    return None


def _row_player(row):
    return (
        row.get("player")
        or row.get("player_name")
        or row.get("name")
    )


def _row_line(row):
    value = (
        row.get("line")
        if row.get("line") is not None
        else row.get("pp_line")
    )

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _game_key(away, home, start_time):
    """
    Stable grouping key for one PrizePicks game.
    """

    dt = _parse_time(start_time)

    if dt:
        time_key = dt.isoformat()
    else:
        time_key = str(start_time or "")

    return (
        _normalize_text(away),
        _normalize_text(home),
        time_key,
    )


# ============================================================
# PRIZEPICKS ROW PREPARATION
# ============================================================

def prepare_pp_market_rows(pp_rows):
    """
    Validate PrizePicks rows before any PropLine calls.

    Returns:
        usable rows
        skipped rows
    """

    usable = []
    skipped = []

    for row in pp_rows:

        player = _row_player(row)
        model_prop = _pp_model_prop(row)
        pp_line = _row_line(row)

        start_time = row.get("start_time")

        away, home = _extract_pp_teams(row)

        reason = None

        if not player:
            reason = "PLAYER_MISSING"

        elif not model_prop:
            reason = "MARKET_UNSUPPORTED"

        elif pp_line is None:
            reason = "PP_LINE_MISSING"

        elif not away or not home:
            reason = "GAME_TEAMS_MISSING"

        elif not start_time:
            reason = "GAME_START_TIME_MISSING"

        if reason:
            skipped.append(
                {
                    "row": row,
                    "market_available": False,
                    "market_reason": reason,
                }
            )
            continue

        usable.append(
            {
                "original_row": row,

                "player": str(player).strip(),

                "model_prop": model_prop,

                "market_key": MLB_MARKET_MAP[
                    model_prop
                ],

                "pp_line": pp_line,

                "away_team": away,
                "home_team": home,

                "start_time": start_time,

                "game_key": _game_key(
                    away,
                    home,
                    start_time,
                ),
            }
        )

    return usable, skipped


# ============================================================
# GAME GROUPING
# ============================================================

def group_pp_rows_by_game(prepared_rows):
    grouped = defaultdict(list)

    for row in prepared_rows:
        grouped[row["game_key"]].append(row)

    return grouped


# ============================================================
# EVENT MATCHING
# ============================================================

def match_pp_games_to_propline(
    grouped_rows,
    events_response,
):
    """
    Match each PrizePicks game ONCE.

    We use:
        away team
        home team
        start time

    No fuzzy guessing.
    """

    matches = {}

    for game_key, rows in grouped_rows.items():

        sample = rows[0]

        result = find_mlb_event(
            away_team=sample["away_team"],
            home_team=sample["home_team"],
            start_time=sample["start_time"],
            events_response=events_response,
        )

        matches[game_key] = result

    return matches


# ============================================================
# ONE PROPLINE REQUEST PER GAME
# ============================================================

def download_game_markets(
    grouped_rows,
    event_matches,
    force_refresh=False,
):
    """
    Download all required markets for each matched game.

    IMPORTANT:
    We do NOT make one request per player.

    If a game has:
        20 hitters
        2 pitchers
        8 prop types

    all required market types are requested together.
    """

    game_data = {}
    errors = []

    for game_key, rows in grouped_rows.items():

        match = event_matches.get(game_key, {})

        if not match.get("matched"):
            game_data[game_key] = None

            errors.append(
                {
                    "game_key": game_key,
                    "reason": match.get(
                        "reason",
                        "EVENT_NOT_MATCHED",
                    ),
                }
            )

            continue

        event_id = match["event_id"]

        markets = sorted(
            {
                row["market_key"]
                for row in rows
            }
        )

        try:
            data = get_mlb_event_odds(
                event_id=event_id,
                markets=markets,
                force_refresh=force_refresh,
            )

            game_data[game_key] = {
                "event_id": event_id,
                "event_match": match,
                "markets_requested": markets,
                "data": data,
            }

        except Exception as exc:

            game_data[game_key] = None

            errors.append(
                {
                    "game_key": game_key,
                    "event_id": event_id,
                    "reason": "PROPLINE_REQUEST_FAILED",
                    "error": str(exc),
                }
            )

    return game_data, errors


# ============================================================
# ATTACH MARKET CONSENSUS
# ============================================================

def attach_market_consensus(
    prepared_rows,
    game_data,
):
    """
    Attach sportsbook consensus to each PrizePicks row using
    the already-downloaded game data.

    ZERO additional PropLine requests occur here.
    """

    results = []

    for row in prepared_rows:

        game = game_data.get(
            row["game_key"]
        )

        base = dict(row["original_row"])

        base["pp_line"] = row["pp_line"]
        base["market_model_prop"] = (
            row["model_prop"]
        )

        if not game:

            base.update(
                {
                    "market_available": False,
                    "market_reason":
                        "GAME_MARKET_UNAVAILABLE",

                    "market_lean": None,
                    "market_probability": None,
                    "market_strength":
                        "UNAVAILABLE",

                    "market_books": 0,
                }
            )

            results.append(base)
            continue

        consensus = build_market_consensus(
            event_data=game["data"],
            player_name=row["player"],
            market_key=row["market_key"],
            pp_line=row["pp_line"],
        )

        base["propline_event_id"] = (
            game["event_id"]
        )

        base["market_available"] = (
            consensus.get(
                "available",
                False,
            )
        )

        base["market_reason"] = (
            consensus.get("reason")
        )

        base["market_lean"] = (
            consensus.get("market_lean")
        )

        base["market_probability"] = (
            consensus.get(
                "market_probability"
            )
        )

        base["market_more_probability"] = (
            consensus.get(
                "market_more_probability"
            )
        )

        base["market_less_probability"] = (
            consensus.get(
                "market_less_probability"
            )
        )

        base["market_strength"] = (
            consensus.get(
                "market_strength",
                "UNAVAILABLE",
            )
        )

        base["market_books"] = (
            consensus.get(
                "books_at_exact_line",
                0,
            )
        )

        base["market_dispersion"] = (
            consensus.get(
                "market_dispersion"
            )
        )

        base["market_outliers_removed"] = len(
            consensus.get(
                "outliers_removed",
                []
            )
        )

        base["market_books_detail"] = (
            consensus.get(
                "books",
                []
            )
        )

        results.append(base)

    return results


# ============================================================
# MODEL + MARKET DECISION
# ============================================================

def apply_model_market_check(row):
    """
    Compare an already-computed MLB model result with
    sportsbook consensus.

    Expected model fields:
        lean
        strongest_probability

    If sportsbook data is unavailable/thin:
        FALLBACK

    This allows the existing PP Market Guard to remain the
    fallback rather than making up sportsbook evidence.
    """

    result = dict(row)

    model_lean = result.get("lean")

    probability = result.get(
        "strongest_probability"
    )

    market_result = {
        "available": result.get(
            "market_available",
            False,
        ),

        "market_lean": result.get(
            "market_lean"
        ),

        "market_probability": result.get(
            "market_probability"
        ),

        "market_strength": result.get(
            "market_strength",
            "INSUFFICIENT",
        ),
    }

    comparison = compare_model_to_market(
        model_lean=model_lean,
        model_probability=probability,
        market_result=market_result,
    )

    result.update(comparison)

    return result


# ============================================================
# FULL BRIDGE
# ============================================================

def enrich_mlb_pp_board_with_market(
    pp_rows,
    force_refresh=False,
):
    """
    Main bridge function.

    Flow:

        PrizePicks rows
            ↓
        validate supported rows
            ↓
        group by game
            ↓
        fetch PropLine event list ONCE
            ↓
        match games
            ↓
        request all needed markets ONCE per game
            ↓
        attach exact-line consensus to every PP row

    This function does NOT run our MLB prediction model.
    It only adds independent market information.
    """

    prepared, skipped = (
        prepare_pp_market_rows(pp_rows)
    )

    if not prepared:

        return {
            "rows": [],
            "skipped": skipped,

            "games": 0,
            "matched_games": 0,

            "market_requests": 0,

            "errors": [],
        }

    grouped = group_pp_rows_by_game(
        prepared
    )

    # ONE events request.
    event_wrapper = get_mlb_events(
        force_refresh=force_refresh
    )

    events_response = event_wrapper.get(
        "data",
        []
    )

    event_matches = (
        match_pp_games_to_propline(
            grouped_rows=grouped,
            events_response=events_response,
        )
    )

    matched_games = sum(
        1
        for match in event_matches.values()
        if match.get("matched")
    )

    game_data, errors = (
        download_game_markets(
            grouped_rows=grouped,
            event_matches=event_matches,
            force_refresh=force_refresh,
        )
    )

    rows = attach_market_consensus(
        prepared_rows=prepared,
        game_data=game_data,
    )

    return {
        "rows": rows,

        "skipped": skipped,

        "games": len(grouped),

        "matched_games": matched_games,

        # At most one odds request per matched game.
        "market_requests": matched_games,

        "event_matches": event_matches,

        "errors": errors,

        "event_api_usage": (
            event_wrapper.get("usage")
        ),
    }
