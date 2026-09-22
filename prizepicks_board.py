import requests
import time
from collections import Counter

# Short-lived PrizePicks board cache
_PP_CACHE = None
_PP_CACHE_TIME = 0.0
PP_CACHE_SECONDS = 60


PRIZEPICKS_URL = (
    "https://partner-api.prizepicks.com/projections?per_page=1000"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}


def _download_prizepicks_board():
    response = requests.get(
        PRIZEPICKS_URL,
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()

    included = payload.get("included", [])

    players = {
        str(item["id"]): item
        for item in included
        if item.get("type") == "new_player"
    }

    # Projection game_id matches the game's external_game_id,
    # not the included object's internal ID.
    games = {}

    for item in included:
        if item.get("type") != "game":
            continue

        game_attrs = item.get("attributes", {})
        external_game_id = game_attrs.get("external_game_id")

        if external_game_id:
            games[str(external_game_id)] = item

    rows = []

    for projection in payload.get("data", []):
        attrs = projection.get("attributes", {})

        league = attrs.get("league_ppid")

        if league not in {"MLB", "WNBA", "NFL"}:
            continue

        if attrs.get("status") != "pre_game":
            continue

        if attrs.get("in_game") is True:
            continue

        relationships = projection.get("relationships", {})

        player_rel = (
            relationships
            .get("new_player", {})
            .get("data")
        )

        if not player_rel:
            continue

        player_record = players.get(
            str(player_rel.get("id"))
        )

        if not player_record:
            continue

        player_attrs = player_record.get("attributes", {})

        player_name = (
            player_attrs.get("name")
            or player_attrs.get("display_name")
            or player_attrs.get("full_name")
        )

        if not player_name:
            continue

        line = attrs.get("line_score")

        if line is None:
            continue

        # Resolve the PrizePicks game object from attrs.game_id.
        projection_game_id = attrs.get("game_id")

        game_record = games.get(
            str(projection_game_id)
        )

        away_team = None
        home_team = None
        game_status = None
        game_start_time = None

        if game_record:
            game_attrs = game_record.get(
                "attributes",
                {},
            )

            game_status = game_attrs.get("status")
            game_start_time = game_attrs.get("start_time")

            metadata = game_attrs.get(
                "metadata",
                {},
            ) or {}

            game_info = metadata.get(
                "game_info",
                {},
            ) or {}

            teams = game_info.get(
                "teams",
                {},
            ) or {}

            away_data = teams.get(
                "away",
                {},
            ) or {}

            home_data = teams.get(
                "home",
                {},
            ) or {}

            away_team = away_data.get(
                "abbreviation"
            )

            home_team = home_data.get(
                "abbreviation"
            )

        rows.append({
            "projection_id": projection.get("id"),
            "player_id": player_rel.get("id"),
            "player": player_name,
            "league": league,
            "prop": attrs.get("stat_type"),
            "display_prop": attrs.get("stat_display_name"),
            "line": line,
            "start_time": attrs.get("start_time"),
            "game_id": attrs.get("game_id"),
            "away_team": away_team,
            "home_team": home_team,
            "game_status": game_status,
            "game_start_time": game_start_time,
            "odds_type": attrs.get("odds_type"),
            "projection_type": attrs.get("projection_type"),
            "event_type": attrs.get("event_type"),
            "description": attrs.get("description"),
            "is_promo": attrs.get("is_promo"),
            "flash_sale_line": attrs.get(
                "flash_sale_line_score"
            ),
            "updated_at": attrs.get("updated_at"),
        })

    return rows


if __name__ == "__main__":

    board = get_prizepicks_board()

    print("PRIZEPICKS BOARD READER")
    print("=" * 80)

    print("Usable MLB/WNBA/NFL records:", len(board))

    counts = Counter(
        row["league"]
        for row in board
    )

    print("\nBY SPORT")

    for league in ["MLB", "WNBA", "NFL"]:
        print(
            f"{league}:",
            counts.get(league, 0)
        )

    print("\nODDS TYPES")

    odds = Counter(
        str(row["odds_type"])
        for row in board
    )

    for name, count in odds.most_common():
        print(name, count)

    print("\nMLB HITTER FANTASY SCORE")
    print("=" * 80)

    hfs = [
        row
        for row in board
        if row["league"] == "MLB"
        and row["prop"] == "Hitter Fantasy Score"
    ]

    for row in hfs:
        print(
            f'{row["player"]:24} | '
            f'Line {str(row["line"]):5} | '
            f'Odds {str(row["odds_type"]):12} | '
            f'Promo {row["is_promo"]} | '
            f'{row["description"]}'
        )

    print("\nHFS records:", len(hfs))


def get_prizepicks_board(force_refresh=False):
    global _PP_CACHE, _PP_CACHE_TIME

    now = time.time()

    if (
        not force_refresh
        and _PP_CACHE is not None
        and (now - _PP_CACHE_TIME) < PP_CACHE_SECONDS
    ):
        return _PP_CACHE

    try:
        board = _download_prizepicks_board()

        _PP_CACHE = board
        _PP_CACHE_TIME = now

        return board

    except requests.HTTPError as exc:
        # If PrizePicks temporarily rate-limits us,
        # use the most recent successful board instead of crashing.
        if (
            exc.response is not None
            and exc.response.status_code == 429
            and _PP_CACHE is not None
        ):
            return _PP_CACHE

        raise


def clear_prizepicks_cache():
    global _PP_CACHE, _PP_CACHE_TIME
    _PP_CACHE = None
    _PP_CACHE_TIME = 0.0


# ============================================================
# SPORTS PROP SUPPORT MAP
# ============================================================

SUPPORTED_PROPS = {
    "MLB": {
        "Hitter Fantasy Score": "hitter_fantasy_score",
        "Hits": "hits",
        "Total Bases": "total_bases",
        "Runs": "runs",
        "RBIs": "rbi",
        "Walks": "walks",

        "Pitcher Strikeouts": "strikeouts",
        "Hits Allowed": "hits_allowed",
        "Walks Allowed": "walks_allowed",
        "Earned Runs Allowed": "earned_runs",
        "Pitching Outs": "pitching_outs",
        "Pitcher Fantasy Score": "pitcher_fantasy_score",
    },

    "WNBA": {
        "Points": "points",
        "Rebounds": "rebounds",
        "Assists": "assists",
        "3-PT Made": "3pm",
        "Pts+Rebs+Asts": "pra",
        "Pts+Rebs": "pr",
        "Pts+Asts": "pa",
        "Rebs+Asts": "ra",
        "Fantasy Score": "fantasy_score",
    },

    # NFL model will be connected later.
    "NFL": {},
}


def get_supported_prop(pp_prop, league):
    return SUPPORTED_PROPS.get(league, {}).get(pp_prop)


def is_supported_prop(pp_prop, league):
    return get_supported_prop(pp_prop, league) is not None


def get_supported_board(league=None, board=None):
    if board is None:
        board = get_prizepicks_board()

    results = []

    for row in board:

        # ==================================================
        # MAIN FULL-GAME PRIZEPICKS LINE ONLY
        # ==================================================
        #
        # PrizePicks can publish multiple "standard" lines for
        # the same player/prop. Some are team_with_duration
        # partial-game lines. Our models project FULL GAMES,
        # so those must never enter the automatic scanner.
        #
        # Keep only:
        #   - standard odds
        #   - full-game team event
        #   - non-promo
        #   - non-flash-sale
        #
        if str(row.get("odds_type") or "").lower() != "standard":
            continue

        if str(row.get("event_type") or "").lower() != "team":
            continue

        if row.get("is_promo"):
            continue

        if row.get("flash_sale_line") is not None:
            continue

        if league and row.get("league") != league:
            continue

        model_prop = get_supported_prop(
            row.get("prop"),
            row.get("league"),
        )

        if model_prop is None:
            continue

        item = dict(row)

        item["model_prop"] = model_prop
        item["supported"] = True

        results.append(item)

    return results
