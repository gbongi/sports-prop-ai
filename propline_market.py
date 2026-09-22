import os
import re
import time
import statistics
import unicodedata
from collections import defaultdict

import requests


# ============================================================
# CONFIG
# ============================================================

PROPLINE_BASE_URL = "https://api.prop-line.com/v1"
PROPLINE_SPORT = "baseball_mlb"

# Keep API usage low.
CACHE_SECONDS = 600  # 10 minutes

_CACHE = {}


# Our MLB model prop -> PropLine market
#
# Runs are intentionally NOT included yet because
# batter_runs_scored did not return a usable market in our test.
MLB_MARKET_MAP = {
    "hits": "batter_hits",
    "total_bases": "batter_total_bases",
    "rbi": "batter_rbis",
    "walks": "batter_walks",

    "strikeouts": "pitcher_strikeouts",
    "hits_allowed": "pitcher_hits_allowed",
    "walks_allowed": "pitcher_walks",
    "earned_runs": "pitcher_earned_runs",
    "pitching_outs": "pitcher_outs",
}


# Sources we do NOT want mixed into sportsbook consensus.
#
# Prediction markets / DFS-style sources should not receive
# the same weight as conventional sportsbook O/U markets.
EXCLUDED_BOOKS = {
    "kalshi",
    "polymarket",
    "polymarket us",
    "underdog",
    "underdog fantasy",
    "prizepicks",
    "sleeper",
    "novig",
}


# Minimum independent books required before we consider the
# sportsbook consensus strong enough to validate a model pick.
MIN_BOOKS_FOR_CONSENSUS = 3


# Odds sanity limits.
#
# We do not automatically reject normal heavily juiced markets,
# but absurd values that are probably malformed are ignored.
MAX_ABS_AMERICAN_ODDS = 5000


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_player_name(value):
    """
    Normalize player names across PrizePicks / PropLine.

    Examples:
        Zebby Matthews
        Zebby Matthews (MIN)

    both become:
        zebby matthews
    """

    if not value:
        return ""

    value = str(value).strip().lower()

    # Convert accented characters to their ASCII base.
    # Example: Narváez -> Narvaez
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )

    # Remove trailing team abbreviation.
    value = re.sub(r"\s*\([^)]*\)\s*$", "", value)

    # Normalize apostrophes before stripping punctuation.
    value = value.replace("’", "'")

    # Remove punctuation.
    value = re.sub(r"[^a-z0-9\s]", "", value)

    # Collapse whitespace.
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_book_name(value):
    if not value:
        return ""

    value = str(value).strip().lower()
    value = re.sub(r"\s+", " ", value)

    return value


def is_excluded_book(book_name):
    normalized = normalize_book_name(book_name)

    return normalized in EXCLUDED_BOOKS


# ============================================================
# ODDS MATH
# ============================================================

def american_to_implied_probability(odds):
    """
    Convert American odds to raw implied probability.
    """

    try:
        odds = float(odds)
    except (TypeError, ValueError):
        return None

    if odds == 0:
        return None

    if abs(odds) > MAX_ABS_AMERICAN_ODDS:
        return None

    if odds < 0:
        return abs(odds) / (abs(odds) + 100.0)

    return 100.0 / (odds + 100.0)


def calculate_no_vig(over_odds, under_odds):
    """
    Convert an Over/Under price pair into fair probabilities
    after removing sportsbook vig.
    """

    p_over = american_to_implied_probability(over_odds)
    p_under = american_to_implied_probability(under_odds)

    if p_over is None or p_under is None:
        return None

    total = p_over + p_under

    if total <= 0:
        return None

    fair_over = p_over / total
    fair_under = p_under / total

    return {
        "more": fair_over,
        "less": fair_under,
        "raw_more": p_over,
        "raw_less": p_under,
        "vig": total - 1.0,
    }


# ============================================================
# API
# ============================================================

def get_mlb_events(force_refresh=False):
    """
    Return the current PropLine MLB event list.
    """

    api_key = os.getenv("PROPLINE_API_KEY")

    if not api_key:
        raise RuntimeError(
            "PROPLINE_API_KEY is not loaded in the environment."
        )

    cache_key = ("mlb_events",)

    now = time.time()

    if not force_refresh and cache_key in _CACHE:
        cached_time, cached_data = _CACHE[cache_key]

        if now - cached_time < CACHE_SECONDS:
            return cached_data

    url = (
        f"{PROPLINE_BASE_URL}/sports/"
        f"{PROPLINE_SPORT}/events"
    )

    response = requests.get(
        url,
        headers={
            "X-API-Key": api_key,
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    result = {
        "data": data,
        "usage": {
            "daily_limit": response.headers.get(
                "X-Daily-Limit"
            ),
            "daily_used": response.headers.get(
                "X-Daily-Used"
            ),
            "daily_remaining": response.headers.get(
                "X-Daily-Remaining"
            ),
        },
    }

    _CACHE[cache_key] = (now, result)

    return result


def get_mlb_event_odds(
    event_id,
    markets=None,
    force_refresh=False,
):
    """
    Download one MLB event.

    Multiple markets can be requested in ONE API call.
    """

    api_key = os.getenv("PROPLINE_API_KEY")

    if not api_key:
        raise RuntimeError(
            "PROPLINE_API_KEY is not loaded in the environment."
        )

    if markets is None:
        markets = sorted(
            set(MLB_MARKET_MAP.values())
        )

    markets = sorted(set(markets))

    cache_key = (
        "mlb_odds",
        str(event_id),
        tuple(markets),
    )

    now = time.time()

    if not force_refresh and cache_key in _CACHE:
        cached_time, cached_data = _CACHE[cache_key]

        if now - cached_time < CACHE_SECONDS:
            return cached_data

    url = (
        f"{PROPLINE_BASE_URL}/sports/"
        f"{PROPLINE_SPORT}/events/"
        f"{event_id}/odds"
    )

    response = requests.get(
        url,
        headers={
            "X-API-Key": api_key,
        },
        params={
            "markets": ",".join(markets),
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    # Keep usage metadata without changing the API structure
    # our parser expects.
    data["_propline_usage"] = {
        "daily_limit": response.headers.get(
            "X-Daily-Limit"
        ),
        "daily_used": response.headers.get(
            "X-Daily-Used"
        ),
        "daily_remaining": response.headers.get(
            "X-Daily-Remaining"
        ),
    }

    _CACHE[cache_key] = (now, data)

    return data


# ============================================================
# RAW MARKET EXTRACTION
# ============================================================

def extract_exact_line_quotes(
    event_data,
    player_name,
    market_key,
    target_line,
):
    """
    Extract ONLY normal Over/Under prices at the exact
    PrizePicks line.

    This automatically ignores:
        alternate lines
        threshold props
        incomplete O/U pairs
        excluded sources
        malformed odds
    """

    normalized_player = normalize_player_name(
        player_name
    )

    try:
        target_line = float(target_line)
    except (TypeError, ValueError):
        return []

    # book -> possible quote pairs
    candidates = defaultdict(list)

    for book in event_data.get("bookmakers", []):

        book_name = (
            book.get("title")
            or book.get("key")
            or "Unknown"
        )

        if is_excluded_book(book_name):
            continue

        for market in book.get("markets", []):

            if market.get("key") != market_key:
                continue

            grouped = defaultdict(dict)

            for outcome in market.get("outcomes", []):

                description = outcome.get(
                    "description"
                )

                if (
                    normalize_player_name(description)
                    != normalized_player
                ):
                    continue

                side = str(
                    outcome.get("name", "")
                ).strip().lower()

                # Reject threshold outcomes like:
                # "3+ Strikeouts"
                if side not in {"over", "under"}:
                    continue

                try:
                    point = float(
                        outcome.get("point")
                    )
                except (TypeError, ValueError):
                    continue

                # Exact PrizePicks line only.
                if abs(point - target_line) > 0.001:
                    continue

                odds = outcome.get("price")

                # Validate odds.
                if (
                    american_to_implied_probability(
                        odds
                    )
                    is None
                ):
                    continue

                grouped[point][side] = odds

            for point, pair in grouped.items():

                if (
                    "over" not in pair
                    or "under" not in pair
                ):
                    continue

                fair = calculate_no_vig(
                    pair["over"],
                    pair["under"],
                )

                if not fair:
                    continue

                candidates[
                    normalize_book_name(book_name)
                ].append(
                    {
                        "book": book_name,
                        "line": point,
                        "over_odds": pair["over"],
                        "under_odds": pair["under"],
                        "no_vig_more": fair["more"],
                        "no_vig_less": fair["less"],
                        "vig": fair["vig"],
                    }
                )

    # ========================================================
    # DEDUPLICATE BOOKS
    # ========================================================
    #
    # If a source appears multiple times, it gets ONE vote.
    #
    # Select the quote with the lowest absolute vig.
    # That generally represents the cleanest two-way market.
    #

    deduplicated = []

    for book_key, quotes in candidates.items():

        if not quotes:
            continue

        best_quote = min(
            quotes,
            key=lambda x: abs(x["vig"]),
        )

        deduplicated.append(best_quote)

    return deduplicated


# ============================================================
# OUTLIER HANDLING
# ============================================================

def remove_probability_outliers(quotes):
    """
    Remove extreme sportsbook probabilities using MAD
    (Median Absolute Deviation).

    MAD is more robust than mean/std when one sportsbook
    posts an extreme number.

    We require at least 5 books before removing anything.
    """

    if len(quotes) < 5:
        return quotes, []

    probabilities = [
        q["no_vig_more"]
        for q in quotes
    ]

    median_probability = statistics.median(
        probabilities
    )

    deviations = [
        abs(p - median_probability)
        for p in probabilities
    ]

    mad = statistics.median(deviations)

    # If books are nearly identical, there is no meaningful
    # outlier structure to detect.
    if mad < 0.005:
        return quotes, []

    # Robust outlier threshold.
    #
    # Also require at least 7 percentage points from median
    # so we don't remove normal sportsbook disagreement.
    threshold = max(
        3.5 * mad,
        0.10,
    )

    kept = []
    removed = []

    for quote in quotes:

        difference = abs(
            quote["no_vig_more"]
            - median_probability
        )

        if difference > threshold:
            removed.append(
                {
                    **quote,
                    "outlier_distance": difference,
                }
            )
        else:
            kept.append(quote)

    # Safety:
    # never let outlier filtering destroy the market.
    if len(kept) < MIN_BOOKS_FOR_CONSENSUS:
        return quotes, []

    return kept, removed


# ============================================================
# CONSENSUS
# ============================================================

def build_market_consensus(
    event_data,
    player_name,
    market_key,
    pp_line,
):
    """
    Build cleaned sportsbook consensus at the EXACT PP line.
    """

    quotes = extract_exact_line_quotes(
        event_data=event_data,
        player_name=player_name,
        market_key=market_key,
        target_line=pp_line,
    )

    if not quotes:
        return {
            "available": False,
            "reason": "NO_EXACT_LINE_MARKET",
            "books_found": 0,
        }

    raw_book_count = len(quotes)

    clean_quotes, outliers = (
        remove_probability_outliers(quotes)
    )

    if not clean_quotes:
        return {
            "available": False,
            "reason": "NO_USABLE_BOOKS",
            "books_found": raw_book_count,
        }

    probabilities = [
        q["no_vig_more"]
        for q in clean_quotes
    ]

    # Median is our primary consensus.
    #
    # This prevents one sportsbook from dragging the
    # entire market probability around.
    market_more = statistics.median(
        probabilities
    )

    market_less = 1.0 - market_more

    # Mean is kept for diagnostics.
    market_more_mean = statistics.mean(
        probabilities
    )

    if len(probabilities) > 1:
        market_dispersion = statistics.pstdev(
            probabilities
        )
    else:
        market_dispersion = 0.0

    if market_more >= 0.52:
        market_lean = "MORE"

    elif market_less >= 0.52:
        market_lean = "LESS"

    else:
        market_lean = "NEUTRAL"

    market_probability = max(
        market_more,
        market_less,
    )

    book_count = len(clean_quotes)

    # ========================================================
    # MARKET QUALITY
    # ========================================================

    if book_count < MIN_BOOKS_FOR_CONSENSUS:

        market_strength = "INSUFFICIENT"

    elif (
        book_count >= 5
        and market_probability >= 0.56
        and market_dispersion <= 0.05
    ):

        market_strength = "STRONG"

    elif (
        market_probability >= 0.53
        and market_dispersion <= 0.07
    ):

        market_strength = "MODERATE"

    else:

        market_strength = "WEAK"

    return {
        "available": True,

        "player": player_name,
        "market": market_key,
        "pp_line": float(pp_line),

        "raw_books": raw_book_count,
        "books_at_exact_line": book_count,

        "market_more_probability": market_more,
        "market_less_probability": market_less,

        "market_more_mean": market_more_mean,

        "market_lean": market_lean,
        "market_probability": market_probability,

        "market_strength": market_strength,

        "market_dispersion": market_dispersion,

        "books": clean_quotes,
        "outliers_removed": outliers,
    }


# ============================================================
# MODEL VS MARKET
# ============================================================

def compare_model_to_market(
    model_lean,
    model_probability,
    market_result,
):
    """
    Compare our independent model with sportsbook consensus.

    IMPORTANT:
    Sportsbooks do not replace our model.
    They act as an independent market validation layer.
    """

    model_lean = str(
        model_lean or "PASS"
    ).upper()

    try:
        model_probability = float(
            model_probability
        )
    except (TypeError, ValueError):

        return {
            "market_check": "MODEL_PROBABILITY_MISSING",
            "market_agreement": None,
            "recommended_action": "PASS",
        }

    if not market_result.get("available"):

        return {
            "market_check": "MARKET_UNAVAILABLE",
            "market_agreement": None,

            # Scanner can fall back to our existing
            # Market Guard V1 instead of blindly passing.
            "recommended_action": "FALLBACK",
        }

    market_lean = market_result.get(
        "market_lean",
        "NEUTRAL",
    )

    market_strength = market_result.get(
        "market_strength",
        "INSUFFICIENT",
    )

    if market_strength == "INSUFFICIENT":

        return {
            "market_check": "INSUFFICIENT_MARKET_DATA",
            "market_agreement": None,
            "recommended_action": "FALLBACK",
        }

    if model_lean not in {"MORE", "LESS"}:

        return {
            "market_check": "MODEL_PASS",
            "market_agreement": None,
            "recommended_action": "PASS",
        }

    # Market near 50/50 should NOT be treated as disagreement.
    if market_lean == "NEUTRAL":

        return {
            "market_check": "MARKET_NEUTRAL",
            "market_agreement": None,
            "recommended_action": model_lean,
        }

    agreement = (
        model_lean == market_lean
    )

    if agreement:

        return {
            "market_check": "MODEL_MARKET_AGREE",
            "market_agreement": True,
            "recommended_action": model_lean,
        }

    # ========================================================
    # DISAGREEMENT
    # ========================================================

    market_probability = market_result.get(
        "market_probability",
        0.50,
    )

    # Strong disagreement:
    # market is clearly leaning the opposite direction.
    if (
        market_strength == "STRONG"
        and market_probability >= 0.56
    ):

        return {
            "market_check": "STRONG_MARKET_DISAGREEMENT",
            "market_agreement": False,
            "recommended_action": "PASS",
        }

    # Moderate disagreement also deserves caution.
    if (
        market_strength == "MODERATE"
        and market_probability >= 0.54
    ):

        return {
            "market_check": "MARKET_DISAGREEMENT",
            "market_agreement": False,
            "recommended_action": "PASS",
        }

    # Weak market disagreement does not automatically
    # override the model.
    return {
        "market_check": "WEAK_MARKET_DISAGREEMENT",
        "market_agreement": False,
        "recommended_action": model_lean,
    }


# ============================================================
# PUBLIC FUNCTION
# ============================================================

def get_mlb_market_consensus(
    event_id,
    player_name,
    model_prop,
    pp_line,
    force_refresh=False,
):
    """
    Main function that the scanner will eventually call.

    Example:

        get_mlb_market_consensus(
            event_id="220278",
            player_name="Zebby Matthews",
            model_prop="strikeouts",
            pp_line=4.5,
        )
    """

    market_key = MLB_MARKET_MAP.get(
        model_prop
    )

    if not market_key:

        return {
            "available": False,
            "reason": "UNSUPPORTED_MARKET",
            "player": player_name,
            "model_prop": model_prop,
            "pp_line": pp_line,
        }

    try:

        event_data = get_mlb_event_odds(
            event_id=event_id,
            markets=[market_key],
            force_refresh=force_refresh,
        )

    except requests.RequestException as exc:

        return {
            "available": False,
            "reason": "PROPLINE_REQUEST_FAILED",
            "error": str(exc),
            "player": player_name,
            "model_prop": model_prop,
            "pp_line": pp_line,
        }

    result = build_market_consensus(
        event_data=event_data,
        player_name=player_name,
        market_key=market_key,
        pp_line=pp_line,
    )

    result["model_prop"] = model_prop

    result["usage"] = event_data.get(
        "_propline_usage"
    )

    return result


# ============================================================
# CACHE
# ============================================================

def clear_propline_cache():
    _CACHE.clear()

# ============================================================
# EVENT MATCHING
# ============================================================

def normalize_team_name(value):
    """
    Normalize team names for matching PrizePicks games
    to PropLine events.
    """
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


def _extract_event_list(events_response):
    """
    PropLine event responses may be a list directly or
    contained inside a data/events field.
    """
    if isinstance(events_response, list):
        return events_response

    if not isinstance(events_response, dict):
        return []

    data = events_response.get("data")

    if isinstance(data, list):
        return data

    events = events_response.get("events")

    if isinstance(events, list):
        return events

    return []


def _parse_event_time(value):
    """Parse ISO event timestamps into timezone-aware datetime."""
    if not value:
        return None

    try:
        from datetime import datetime

        value = str(value).strip()

        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        return datetime.fromisoformat(value)

    except (TypeError, ValueError):
        return None


def find_mlb_event(
    away_team,
    home_team,
    start_time=None,
    events_response=None,
    force_refresh=False,
):
    """
    Match PrizePicks game to PropLine using:

        1. away team
        2. home team
        3. game start time when available

    We refuse ambiguous matches rather than guessing.
    """

    if events_response is None:
        wrapper = get_mlb_events(
            force_refresh=force_refresh
        )
        events_response = wrapper.get("data", [])

    events = _extract_event_list(events_response)

    target_away = normalize_team_name(away_team)
    target_home = normalize_team_name(home_team)

    if not target_away or not target_home:
        return {
            "matched": False,
            "reason": "TEAM_NAME_MISSING",
        }

    team_matches = []

    for event in events:
        event_away = normalize_team_name(
            event.get("away_team")
        )
        event_home = normalize_team_name(
            event.get("home_team")
        )

        if (
            event_away == target_away
            and event_home == target_home
        ):
            team_matches.append(event)

    if not team_matches:
        return {
            "matched": False,
            "reason": "EVENT_NOT_FOUND",
            "away_team": away_team,
            "home_team": home_team,
        }

    # If teams alone uniquely identify the event,
    # no further filtering is necessary.
    if len(team_matches) == 1:
        event = team_matches[0]

        return {
            "matched": True,
            "event_id": str(event.get("id")),
            "away_team": event.get("away_team"),
            "home_team": event.get("home_team"),
            "commence_time": event.get("commence_time"),
            "event": event,
            "match_method": "TEAMS",
        }

    # Multiple games with same teams:
    # start time is required to safely distinguish them.
    target_time = _parse_event_time(start_time)

    if target_time is None:
        return {
            "matched": False,
            "reason": "MULTIPLE_EVENT_MATCHES",
            "matches": team_matches,
            "needs_start_time": True,
        }

    timed_matches = []

    for event in team_matches:
        event_time = _parse_event_time(
            event.get("commence_time")
        )

        if event_time is None:
            continue

        try:
            difference_seconds = abs(
                (event_time - target_time).total_seconds()
            )
        except TypeError:
            continue

        # Allow up to 30 minutes difference in case
        # providers publish slightly different start times.
        if difference_seconds <= 1800:
            timed_matches.append(
                (difference_seconds, event)
            )

    if not timed_matches:
        return {
            "matched": False,
            "reason": "EVENT_TIME_NOT_FOUND",
            "away_team": away_team,
            "home_team": home_team,
            "start_time": start_time,
            "team_matches": team_matches,
        }

    timed_matches.sort(
        key=lambda item: item[0]
    )

    # If two events somehow have exactly the same closest
    # timestamp, refuse to guess.
    if (
        len(timed_matches) > 1
        and timed_matches[0][0] == timed_matches[1][0]
    ):
        return {
            "matched": False,
            "reason": "AMBIGUOUS_EVENT_TIME",
            "matches": [
                item[1]
                for item in timed_matches
            ],
        }

    difference_seconds, event = timed_matches[0]

    return {
        "matched": True,
        "event_id": str(event.get("id")),
        "away_team": event.get("away_team"),
        "home_team": event.get("home_team"),
        "commence_time": event.get("commence_time"),
        "event": event,
        "match_method": "TEAMS_AND_TIME",
        "time_difference_seconds": difference_seconds,
    }


def get_mlb_market_for_game(
    away_team,
    home_team,
    player_name,
    model_prop,
    pp_line,
    start_time=None,
    events_response=None,
    force_refresh=False,
):
    """
    High-level market lookup.

    Game
      -> PropLine event
      -> player
      -> market
      -> exact PrizePicks line
      -> cleaned sportsbook consensus
    """

    event_match = find_mlb_event(
        away_team=away_team,
        home_team=home_team,
        start_time=start_time,
        events_response=events_response,
        force_refresh=force_refresh,
    )

    if not event_match.get("matched"):
        return {
            "available": False,
            "reason": event_match.get(
                "reason",
                "EVENT_NOT_FOUND",
            ),
            "event_match": event_match,
            "player": player_name,
            "model_prop": model_prop,
            "pp_line": pp_line,
        }

    result = get_mlb_market_consensus(
        event_id=event_match["event_id"],
        player_name=player_name,
        model_prop=model_prop,
        pp_line=pp_line,
        force_refresh=force_refresh,
    )

    result["event_id"] = event_match["event_id"]
    result["event_away_team"] = (
        event_match["away_team"]
    )
    result["event_home_team"] = (
        event_match["home_team"]
    )
    result["event_commence_time"] = (
        event_match["commence_time"]
    )

    return result


# ============================================================
# MLB TEAM ALIASES
# ============================================================

MLB_TEAM_ALIASES = {
    "ARI": "Arizona Diamondbacks",
    "AZ": "Arizona Diamondbacks",
    "ATL": "Atlanta Braves",
    "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox",
    "CHC": "Chicago Cubs",
    "CWS": "Chicago White Sox",
    "CHW": "Chicago White Sox",
    "CIN": "Cincinnati Reds",
    "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies",
    "DET": "Detroit Tigers",
    "HOU": "Houston Astros",
    "KC": "Kansas City Royals",
    "KCR": "Kansas City Royals",
    "LAA": "Los Angeles Angels",
    "LAD": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",
    "NYM": "New York Mets",
    "NYY": "New York Yankees",
    "ATH": "Athletics",
    "OAK": "Athletics",
    "PHI": "Philadelphia Phillies",
    "PIT": "Pittsburgh Pirates",
    "SD": "San Diego Padres",
    "SDP": "San Diego Padres",
    "SEA": "Seattle Mariners",
    "SF": "San Francisco Giants",
    "SFG": "San Francisco Giants",
    "STL": "St. Louis Cardinals",
    "TB": "Tampa Bay Rays",
    "TBR": "Tampa Bay Rays",
    "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",
    "WSH": "Washington Nationals",
    "WAS": "Washington Nationals",
}


def expand_mlb_team_name(team):
    """
    Convert PrizePicks/MLB abbreviations to the full team
    names used by PropLine.

    Full names pass through unchanged.
    """
    if not team:
        return team

    raw = str(team).strip()
    upper = raw.upper()

    return MLB_TEAM_ALIASES.get(
        upper,
        raw,
    )


# Preserve the original time-aware matcher.
_find_mlb_event_time_aware = find_mlb_event


def find_mlb_event(
    away_team,
    home_team,
    start_time=None,
    events_response=None,
    force_refresh=False,
):
    """
    MLB event matcher with explicit team-alias expansion
    followed by the existing time-aware matching logic.
    """

    away_team = expand_mlb_team_name(
        away_team
    )

    home_team = expand_mlb_team_name(
        home_team
    )

    return _find_mlb_event_time_aware(
        away_team=away_team,
        home_team=home_team,
        start_time=start_time,
        events_response=events_response,
        force_refresh=force_refresh,
    )
