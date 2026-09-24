"""
MLB Matchup Engine V2
---------------------
Baseball-first profile layer for Sports Prop AI.

This module DOES NOT make PrizePicks picks yet.
It builds hitter/pitcher profiles for the future:

pitcher x hitter
-> K / BB / HBP / ball-in-play
-> GB / LD / FB
-> 1B / 2B / 3B / HR / out
-> baserunning
-> game simulation
-> prop distributions
-> HFS / PFS

Market data does not belong in this module.
Missing statistics are never invented.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, Optional

from mlb_model import (
    find_player,
    player_game_log,
    _person_details,
)


def _f(value, default=0.0):
    try:
        if value in (None, "", "-", ".---"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_f(value):
    try:
        if value in (None, "", "-", ".---"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_div(num, den):
    num = _f(num)
    den = _f(den)

    if den <= 0:
        return None

    return num / den


def _weighted_rate(
    games: Iterable[dict],
    numerator_fn,
    denominator_fn,
    decay=0.97,
):
    rows = list(games)

    weighted_num = 0.0
    weighted_den = 0.0

    for i, game in enumerate(rows):
        weight = decay ** (len(rows) - 1 - i)

        num = _f(numerator_fn(game))
        den = _f(denominator_fn(game))

        if den <= 0:
            continue

        weighted_num += num * weight
        weighted_den += den * weight

    if weighted_den <= 0:
        return None

    return weighted_num / weighted_den


def _sum_stat(games, key):
    return sum(
        _f((g.get("stat") or {}).get(key))
        for g in games
    )


def _plate_appearances(stat):
    pa = _optional_f(stat.get("plateAppearances"))

    if pa is not None:
        return pa

    return (
        _f(stat.get("atBats"))
        + _f(stat.get("baseOnBalls"))
        + _f(stat.get("hitByPitch"))
        + _f(stat.get("sacFlies"))
        + _f(stat.get("sacBunts"))
    )


def _batters_faced(stat):
    bf = _optional_f(stat.get("battersFaced"))

    if bf is not None:
        return bf

    # Do not invent BF from IP/hits/walks because that would
    # silently ignore errors, HBP, double plays, etc.
    return 0.0


def _batted_ball_rates(games):
    """
    Use MLB game-log batted-ball fields only when they are
    actually supplied by the API.

    If unavailable, return None. Statcast will fill this later.
    """

    keys = {
        "ground_outs": "groundOuts",
        "air_outs": "airOuts",
    }

    totals = {
        name: _sum_stat(games, key)
        for name, key in keys.items()
    }

    total = (
        totals["ground_outs"]
        + totals["air_outs"]
    )

    if total <= 0:
        return {
            "ground_out_rate": None,
            "air_out_rate": None,
            "source": "UNAVAILABLE",
        }

    return {
        "ground_out_rate":
            totals["ground_outs"] / total,

        "air_out_rate":
            totals["air_outs"] / total,

        "source": "MLB_GAME_LOG_OUTS_ONLY",
    }


@dataclass
class HitterProfile:
    player_id: int
    name: str
    bat_side: Optional[str]
    season: int
    games: int

    plate_appearances: float
    at_bats: float

    hits: float
    singles: float
    doubles: float
    triples: float
    home_runs: float

    walks: float
    hit_by_pitch: float
    strikeouts: float

    stolen_bases: float
    caught_stealing: float

    k_rate: Optional[float]
    bb_rate: Optional[float]
    hbp_rate: Optional[float]

    hit_rate_per_ab: Optional[float]
    hr_rate_per_pa: Optional[float]
    xbh_rate_per_ab: Optional[float]

    sb_attempt_rate_per_reach: Optional[float]
    sb_success_rate: Optional[float]

    recent_k_rate: Optional[float]
    recent_bb_rate: Optional[float]
    recent_hit_rate: Optional[float]
    recent_hr_rate: Optional[float]

    ground_out_rate: Optional[float]
    air_out_rate: Optional[float]
    batted_ball_source: str

    statcast_ready: bool = False


@dataclass
class PitcherProfile:
    player_id: int
    name: str
    pitch_hand: Optional[str]
    season: int
    games: int

    batters_faced: float
    strikeouts: float
    walks: float
    hit_by_pitch: float
    hits_allowed: float
    home_runs_allowed: float
    earned_runs: float

    k_rate: Optional[float]
    bb_rate: Optional[float]
    hbp_rate: Optional[float]
    hit_rate: Optional[float]
    hr_rate: Optional[float]

    recent_k_rate: Optional[float]
    recent_bb_rate: Optional[float]
    recent_hit_rate: Optional[float]
    recent_hr_rate: Optional[float]

    ground_out_rate: Optional[float]
    air_out_rate: Optional[float]
    batted_ball_source: str

    statcast_ready: bool = False


_PROFILE_CACHE: Dict[tuple, dict] = {}


def clear_matchup_profile_cache():
    _PROFILE_CACHE.clear()


def _cached(key):
    value = _PROFILE_CACHE.get(key)

    if value is None:
        return None

    return deepcopy(value)


def _store(key, value):
    _PROFILE_CACHE[key] = deepcopy(value)
    return deepcopy(value)


def build_hitter_profile(
    player_name,
    season,
    recent_games=20,
):
    key = (
        "hitter",
        str(player_name).strip().lower(),
        int(season),
        int(recent_games),
    )

    cached = _cached(key)

    if cached is not None:
        return cached

    person = find_player(player_name)

    if not person:
        raise ValueError(
            f"MLB hitter not found: {player_name}"
        )

    player_id = int(person["id"])

    details = _person_details(player_id) or {}

    games = player_game_log(
        player_id,
        int(season),
        "hitting",
    )

    if not games:
        raise ValueError(
            f"No hitting game log for {player_name}"
        )

    pa = sum(
        _plate_appearances(g.get("stat") or {})
        for g in games
    )

    ab = _sum_stat(games, "atBats")
    hits = _sum_stat(games, "hits")
    doubles = _sum_stat(games, "doubles")
    triples = _sum_stat(games, "triples")
    hr = _sum_stat(games, "homeRuns")

    singles = max(
        0.0,
        hits - doubles - triples - hr,
    )

    walks = _sum_stat(games, "baseOnBalls")
    hbp = _sum_stat(games, "hitByPitch")
    strikeouts = _sum_stat(games, "strikeOuts")

    sb = _sum_stat(games, "stolenBases")
    cs = _sum_stat(games, "caughtStealing")

    # Approximate opportunities to initiate a steal.
    # This is NOT P(SB). It is only a descriptive runner
    # tendency denominator and will later be replaced by
    # explicit base-state simulation.
    reaches = (
        hits
        + walks
        + hbp
    )

    attempts = sb + cs

    recent = games[-int(recent_games):]

    batted = _batted_ball_rates(games)

    profile = HitterProfile(
        player_id=player_id,
        name=details.get("name")
            or person.get("fullName")
            or player_name,
        bat_side=details.get("bat_side"),
        season=int(season),
        games=len(games),

        plate_appearances=pa,
        at_bats=ab,

        hits=hits,
        singles=singles,
        doubles=doubles,
        triples=triples,
        home_runs=hr,

        walks=walks,
        hit_by_pitch=hbp,
        strikeouts=strikeouts,

        stolen_bases=sb,
        caught_stealing=cs,

        k_rate=_safe_div(strikeouts, pa),
        bb_rate=_safe_div(walks, pa),
        hbp_rate=_safe_div(hbp, pa),

        hit_rate_per_ab=_safe_div(hits, ab),
        hr_rate_per_pa=_safe_div(hr, pa),
        xbh_rate_per_ab=_safe_div(
            doubles + triples + hr,
            ab,
        ),

        sb_attempt_rate_per_reach=_safe_div(
            attempts,
            reaches,
        ),

        sb_success_rate=_safe_div(
            sb,
            attempts,
        ),

        recent_k_rate=_weighted_rate(
            recent,
            lambda g: (g.get("stat") or {})
                .get("strikeOuts"),
            lambda g: _plate_appearances(
                g.get("stat") or {}
            ),
        ),

        recent_bb_rate=_weighted_rate(
            recent,
            lambda g: (g.get("stat") or {})
                .get("baseOnBalls"),
            lambda g: _plate_appearances(
                g.get("stat") or {}
            ),
        ),

        recent_hit_rate=_weighted_rate(
            recent,
            lambda g: (g.get("stat") or {})
                .get("hits"),
            lambda g: (g.get("stat") or {})
                .get("atBats"),
        ),

        recent_hr_rate=_weighted_rate(
            recent,
            lambda g: (g.get("stat") or {})
                .get("homeRuns"),
            lambda g: _plate_appearances(
                g.get("stat") or {}
            ),
        ),

        ground_out_rate=
            batted["ground_out_rate"],

        air_out_rate=
            batted["air_out_rate"],

        batted_ball_source=
            batted["source"],
    )

    result = asdict(profile)

    return _store(key, result)


def build_pitcher_profile(
    player_name,
    season,
    recent_games=10,
):
    key = (
        "pitcher",
        str(player_name).strip().lower(),
        int(season),
        int(recent_games),
    )

    cached = _cached(key)

    if cached is not None:
        return cached

    person = find_player(player_name)

    if not person:
        raise ValueError(
            f"MLB pitcher not found: {player_name}"
        )

    player_id = int(person["id"])

    details = _person_details(player_id) or {}

    games = player_game_log(
        player_id,
        int(season),
        "pitching",
    )

    if not games:
        raise ValueError(
            f"No pitching game log for {player_name}"
        )

    bf = sum(
        _batters_faced(g.get("stat") or {})
        for g in games
    )

    strikeouts = _sum_stat(games, "strikeOuts")
    walks = _sum_stat(games, "baseOnBalls")
    hbp = _sum_stat(games, "hitBatsmen")
    hits = _sum_stat(games, "hits")
    hr = _sum_stat(games, "homeRuns")
    er = _sum_stat(games, "earnedRuns")

    recent = games[-int(recent_games):]

    batted = _batted_ball_rates(games)

    profile = PitcherProfile(
        player_id=player_id,
        name=details.get("name")
            or person.get("fullName")
            or player_name,
        pitch_hand=details.get("pitch_hand"),
        season=int(season),
        games=len(games),

        batters_faced=bf,
        strikeouts=strikeouts,
        walks=walks,
        hit_by_pitch=hbp,
        hits_allowed=hits,
        home_runs_allowed=hr,
        earned_runs=er,

        k_rate=_safe_div(strikeouts, bf),
        bb_rate=_safe_div(walks, bf),
        hbp_rate=_safe_div(hbp, bf),
        hit_rate=_safe_div(hits, bf),
        hr_rate=_safe_div(hr, bf),

        recent_k_rate=_weighted_rate(
            recent,
            lambda g: (g.get("stat") or {})
                .get("strikeOuts"),
            lambda g: _batters_faced(
                g.get("stat") or {}
            ),
        ),

        recent_bb_rate=_weighted_rate(
            recent,
            lambda g: (g.get("stat") or {})
                .get("baseOnBalls"),
            lambda g: _batters_faced(
                g.get("stat") or {}
            ),
        ),

        recent_hit_rate=_weighted_rate(
            recent,
            lambda g: (g.get("stat") or {})
                .get("hits"),
            lambda g: _batters_faced(
                g.get("stat") or {}
            ),
        ),

        recent_hr_rate=_weighted_rate(
            recent,
            lambda g: (g.get("stat") or {})
                .get("homeRuns"),
            lambda g: _batters_faced(
                g.get("stat") or {}
            ),
        ),

        ground_out_rate=
            batted["ground_out_rate"],

        air_out_rate=
            batted["air_out_rate"],

        batted_ball_source=
            batted["source"],
    )

    result = asdict(profile)

    return _store(key, result)


def matchup_profile_summary(
    hitter_name,
    pitcher_name,
    season,
):
    """
    Data audit only.

    No prediction is produced yet.
    """

    hitter = build_hitter_profile(
        hitter_name,
        season,
    )

    pitcher = build_pitcher_profile(
        pitcher_name,
        season,
    )

    return {
        "season": int(season),
        "hitter": hitter,
        "pitcher": pitcher,

        "ready_for_interaction_model": all([
            hitter.get("k_rate") is not None,
            hitter.get("bb_rate") is not None,
            pitcher.get("k_rate") is not None,
            pitcher.get("bb_rate") is not None,
        ]),

        "market_used": False,

        "note": (
            "Profile layer only. No MORE/LESS "
            "prediction is produced by this module yet."
        ),
    }


def _pct(value):
    if value is None:
        return "N/A"
    return f"{100.0 * value:.1f}%"


def print_matchup_audit(result):
    h = result["hitter"]
    p = result["pitcher"]

    print()
    print("=" * 72)
    print("MLB MATCHUP ENGINE V2 — PROFILE AUDIT")
    print("=" * 72)

    print(
        f"HITTER: {h['name']} "
        f"({h.get('bat_side') or '?'})"
    )

    print(
        "  PA:",
        int(h["plate_appearances"]),
        "| K%:",
        _pct(h["k_rate"]),
        "| BB%:",
        _pct(h["bb_rate"]),
        "| AVG:",
        _pct(h["hit_rate_per_ab"]),
    )

    print(
        "  HR/PA:",
        _pct(h["hr_rate_per_pa"]),
        "| XBH/AB:",
        _pct(h["xbh_rate_per_ab"]),
    )

    print(
        "  SB attempts/reach:",
        _pct(h["sb_attempt_rate_per_reach"]),
        "| SB success:",
        _pct(h["sb_success_rate"]),
    )

    print(
        "  Recent K%:",
        _pct(h["recent_k_rate"]),
        "| Recent BB%:",
        _pct(h["recent_bb_rate"]),
    )

    print(
        "  GB-out:",
        _pct(h["ground_out_rate"]),
        "| Air-out:",
        _pct(h["air_out_rate"]),
        "| Source:",
        h["batted_ball_source"],
    )

    print()

    print(
        f"PITCHER: {p['name']} "
        f"({p.get('pitch_hand') or '?'})"
    )

    print(
        "  BF:",
        int(p["batters_faced"]),
        "| K%:",
        _pct(p["k_rate"]),
        "| BB%:",
        _pct(p["bb_rate"]),
    )

    print(
        "  H/BF:",
        _pct(p["hit_rate"]),
        "| HR/BF:",
        _pct(p["hr_rate"]),
    )

    print(
        "  Recent K%:",
        _pct(p["recent_k_rate"]),
        "| Recent BB%:",
        _pct(p["recent_bb_rate"]),
    )

    print(
        "  GB-out:",
        _pct(p["ground_out_rate"]),
        "| Air-out:",
        _pct(p["air_out_rate"]),
        "| Source:",
        p["batted_ball_source"],
    )

    print()

    print(
        "Interaction model ready:",
        result["ready_for_interaction_model"],
    )

    print("Market used:", result["market_used"])
    print(result["note"])
    print("=" * 72)


if __name__ == "__main__":
    import argparse
    from datetime import datetime

    parser = argparse.ArgumentParser()

    parser.add_argument("hitter")
    parser.add_argument("pitcher")

    parser.add_argument(
        "--season",
        type=int,
        default=datetime.now().year,
    )

    args = parser.parse_args()

    audit = matchup_profile_summary(
        args.hitter,
        args.pitcher,
        args.season,
    )

    print_matchup_audit(audit)


# ============================================================
# STEP 2 — HITTER x PITCHER INTERACTION ENGINE
# ============================================================

def _clamp(value, low, high):
    return max(low, min(high, value))


def _blend_long_recent(
    long_rate,
    recent_rate,
    recent_weight=0.20,
):
    """
    Recent performance is useful, but must not overpower
    the larger season sample.
    """

    if long_rate is None:
        return recent_rate

    if recent_rate is None:
        return long_rate

    return (
        long_rate * (1.0 - recent_weight)
        + recent_rate * recent_weight
    )


def _matchup_rate(
    hitter_rate,
    pitcher_rate,
    hitter_recent=None,
    pitcher_recent=None,
    floor=0.001,
    ceiling=0.95,
):
    """
    Conservative hitter x pitcher interaction.

    Step 2 deliberately avoids pretending we have a perfect
    league-adjusted matchup model before the calibration layer
    exists.

    1. Stabilize each player's rate with recent information.
    2. Combine hitter and pitcher equally.
    3. Keep probabilities inside realistic bounds.

    Later calibration/backtesting can learn better weights.
    """

    hitter_skill = _blend_long_recent(
        hitter_rate,
        hitter_recent,
        0.20,
    )

    pitcher_skill = _blend_long_recent(
        pitcher_rate,
        pitcher_recent,
        0.20,
    )

    available = [
        x
        for x in (
            hitter_skill,
            pitcher_skill,
        )
        if x is not None
    ]

    if not available:
        return None

    probability = (
        sum(available)
        / len(available)
    )

    return _clamp(
        probability,
        floor,
        ceiling,
    )


def _normalize_primary_pa_outcomes(
    k,
    bb,
    hbp,
):
    """
    K, BB and HBP are mutually exclusive terminal PA outcomes.

    Whatever probability remains becomes BALL IN PLAY / OTHER.

    This prevents us from stacking independent percentages
    that sum above 100%.
    """

    k = max(0.0, k or 0.0)
    bb = max(0.0, bb or 0.0)
    hbp = max(0.0, hbp or 0.0)

    terminal = k + bb + hbp

    # Safety cap. We should almost never approach this,
    # but malformed source data must not break probabilities.
    if terminal > 0.85:
        scale = 0.85 / terminal

        k *= scale
        bb *= scale
        hbp *= scale

    bip = max(
        0.0,
        1.0 - k - bb - hbp,
    )

    return {
        "strikeout": k,
        "walk": bb,
        "hit_by_pitch": hbp,
        "ball_in_play_or_other": bip,
    }


def _contact_direction_profile(
    hitter,
    pitcher,
):
    """
    Preliminary contact-direction estimate.

    IMPORTANT:
    MLB game logs currently give us ground OUT / air OUT
    information, not complete Statcast GB/LD/FB data.

    Therefore this is diagnostic only.

    We DO NOT invent line-drive probability here.
    True GB / LD / FB probabilities will be added from
    richer batted-ball data in the next data upgrade.
    """

    h_ground = hitter.get(
        "ground_out_rate"
    )

    p_ground = pitcher.get(
        "ground_out_rate"
    )

    available_ground = [
        x
        for x in (
            h_ground,
            p_ground,
        )
        if x is not None
    ]

    if not available_ground:
        return {
            "ground_out_contact_share": None,
            "air_out_contact_share": None,
            "line_drive_share": None,
            "source":
                "INSUFFICIENT_BATTED_BALL_DATA",
            "simulation_ready": False,
        }

    ground = (
        sum(available_ground)
        / len(available_ground)
    )

    ground = _clamp(
        ground,
        0.05,
        0.95,
    )

    return {
        "ground_out_contact_share":
            ground,

        "air_out_contact_share":
            1.0 - ground,

        "line_drive_share":
            None,

        "source":
            "MLB_GAME_LOG_OUTS_ONLY",

        "simulation_ready":
            False,
    }


def hitter_pitcher_interaction(
    hitter_name,
    pitcher_name,
    season,
):
    """
    Build matchup-specific PA probabilities.

    No PrizePicks line.
    No MORE/LESS.
    No sportsbook/market information.

    Output is baseball-event probability only.
    """

    hitter = build_hitter_profile(
        hitter_name,
        season,
    )

    pitcher = build_pitcher_profile(
        pitcher_name,
        season,
    )

    # --------------------------------------------------------
    # STRIKEOUT
    # --------------------------------------------------------

    p_k = _matchup_rate(
        hitter.get("k_rate"),
        pitcher.get("k_rate"),

        hitter.get(
            "recent_k_rate"
        ),

        pitcher.get(
            "recent_k_rate"
        ),

        floor=0.03,
        ceiling=0.55,
    )

    # --------------------------------------------------------
    # WALK
    # --------------------------------------------------------

    p_bb = _matchup_rate(
        hitter.get("bb_rate"),
        pitcher.get("bb_rate"),

        hitter.get(
            "recent_bb_rate"
        ),

        pitcher.get(
            "recent_bb_rate"
        ),

        floor=0.01,
        ceiling=0.30,
    )

    # --------------------------------------------------------
    # HBP
    # --------------------------------------------------------

    p_hbp = _matchup_rate(
        hitter.get("hbp_rate"),
        pitcher.get("hbp_rate"),

        floor=0.001,
        ceiling=0.08,
    )

    outcomes = (
        _normalize_primary_pa_outcomes(
            p_k,
            p_bb,
            p_hbp,
        )
    )

    contact = (
        _contact_direction_profile(
            hitter,
            pitcher,
        )
    )

    return {
        "season": int(season),

        "hitter": {
            "id":
                hitter["player_id"],

            "name":
                hitter["name"],

            "bat_side":
                hitter.get("bat_side"),
        },

        "pitcher": {
            "id":
                pitcher["player_id"],

            "name":
                pitcher["name"],

            "pitch_hand":
                pitcher.get(
                    "pitch_hand"
                ),
        },

        "plate_appearance": outcomes,

        "contact_direction":
            contact,

        "hitter_inputs": {
            "season_k_rate":
                hitter.get("k_rate"),

            "recent_k_rate":
                hitter.get(
                    "recent_k_rate"
                ),

            "season_bb_rate":
                hitter.get("bb_rate"),

            "recent_bb_rate":
                hitter.get(
                    "recent_bb_rate"
                ),
        },

        "pitcher_inputs": {
            "season_k_rate":
                pitcher.get("k_rate"),

            "recent_k_rate":
                pitcher.get(
                    "recent_k_rate"
                ),

            "season_bb_rate":
                pitcher.get("bb_rate"),

            "recent_bb_rate":
                pitcher.get(
                    "recent_bb_rate"
                ),
        },

        "market_used": False,

        "prediction_created": False,

        "limitations": [
            (
                "Pitch arsenal matchup "
                "not added yet."
            ),
            (
                "True Statcast GB/LD/FB "
                "distribution not added yet."
            ),
            (
                "Contact quality / xBA / xSLG "
                "not added yet."
            ),
            (
                "Bullpen not added yet."
            ),
            (
                "Park/weather not added yet."
            ),
        ],
    }


def print_interaction_audit(result):
    pa = result[
        "plate_appearance"
    ]

    contact = result[
        "contact_direction"
    ]

    h = result["hitter"]
    p = result["pitcher"]

    print()
    print("=" * 72)
    print(
        "STEP 2 — HITTER x PITCHER "
        "INTERACTION AUDIT"
    )
    print("=" * 72)

    print(
        f"{h['name']} "
        f"({h.get('bat_side') or '?'})"
    )

    print(
        "vs"
    )

    print(
        f"{p['name']} "
        f"({p.get('pitch_hand') or '?'})"
    )

    print()

    print(
        "P(K):",
        _pct(pa["strikeout"]),
    )

    print(
        "P(BB):",
        _pct(pa["walk"]),
    )

    print(
        "P(HBP):",
        _pct(
            pa["hit_by_pitch"]
        ),
    )

    print(
        "P(BIP/OTHER):",
        _pct(
            pa[
                "ball_in_play_or_other"
            ]
        ),
    )

    print()

    print(
        "Ground-out contact share:",
        _pct(
            contact[
                "ground_out_contact_share"
            ]
        ),
    )

    print(
        "Air-out contact share:",
        _pct(
            contact[
                "air_out_contact_share"
            ]
        ),
    )

    print(
        "True LD share:",
        (
            _pct(
                contact[
                    "line_drive_share"
                ]
            )
            if contact[
                "line_drive_share"
            ] is not None
            else "NOT YET AVAILABLE"
        ),
    )

    print()

    total = sum(
        pa.values()
    )

    print(
        "PA probability total:",
        f"{total:.6f}",
    )

    print(
        "Market used:",
        result["market_used"],
    )

    print(
        "PrizePicks prediction created:",
        result[
            "prediction_created"
        ],
    )

    print("=" * 72)




# ============================================================
# STEP 3B — STATCAST CONTACT / PITCH PROFILE
# ============================================================

import csv as _csv
import io as _io
import time as _time
import urllib.parse as _urlparse
import urllib.request as _urlrequest
from collections import Counter as _Counter
from copy import deepcopy as _deepcopy


_STATCAST_CACHE = {}
_STATCAST_CACHE_TTL = 1800


def _clean_statcast_column(name):
    return str(name or "").strip().strip('"').strip()


def _clean_statcast_row(row):
    return {
        _clean_statcast_column(k): v
        for k, v in row.items()
    }


def _statcast_float(value):
    try:
        if value in (
            None,
            "",
            "null",
            "None",
        ):
            return None

        return float(value)

    except (TypeError, ValueError):
        return None


def _statcast_cache_get(key):
    item = _STATCAST_CACHE.get(key)

    if not item:
        return None

    created, value = item

    if (
        _time.monotonic() - created
        > _STATCAST_CACHE_TTL
    ):
        _STATCAST_CACHE.pop(
            key,
            None,
        )
        return None

    return _deepcopy(value)


def _statcast_cache_set(
    key,
    value,
):
    _STATCAST_CACHE[key] = (
        _time.monotonic(),
        _deepcopy(value),
    )

    return _deepcopy(value)


def clear_statcast_cache():
    _STATCAST_CACHE.clear()


def _statcast_download(
    player_id,
    role,
    start_date,
    end_date,
    timeout=45,
):
    role = str(role).lower()

    if role not in (
        "batter",
        "pitcher",
    ):
        raise ValueError(
            "role must be batter or pitcher"
        )

    lookup_field = (
        "batters_lookup[]"
        if role == "batter"
        else "pitchers_lookup[]"
    )

    key = (
        int(player_id),
        role,
        str(start_date),
        str(end_date),
    )

    cached = _statcast_cache_get(
        key
    )

    if cached is not None:
        return cached

    params = {
        "all": "true",
        "type": role,
        "player_type": role,
        lookup_field:
            str(int(player_id)),
        "game_date_gt":
            str(start_date),
        "game_date_lt":
            str(end_date),
    }

    url = (
        "https://baseballsavant.mlb.com/"
        "statcast_search/csv?"
        + _urlparse.urlencode(
            params,
            doseq=True,
        )
    )

    req = _urlrequest.Request(
        url,
        headers={
            "User-Agent":
                "Mozilla/5.0",

            "Accept":
                "text/csv,*/*",

            "Accept-Encoding":
                "identity",

            "Connection":
                "close",
        },
    )

    started = _time.time()

    with _urlrequest.urlopen(
        req,
        timeout=timeout,
    ) as response:
        raw = response.read()

    elapsed = (
        _time.time() - started
    )

    text = raw.decode(
        "utf-8",
        errors="replace",
    )

    reader = _csv.DictReader(
        _io.StringIO(text)
    )

    rows = [
        _clean_statcast_row(row)
        for row in reader
    ]

    expected_id = str(
        int(player_id)
    )

    id_field = (
        "batter"
        if role == "batter"
        else "pitcher"
    )

    rows = [
        row
        for row in rows
        if str(
            row.get(
                id_field,
                "",
            )
        ).strip()
        == expected_id
    ]

    result = {
        "rows": rows,
        "seconds":
            elapsed,
        "bytes":
            len(raw),
        "source":
            "BASEBALL_SAVANT_STATCAST",
    }

    return _statcast_cache_set(
        key,
        result,
    )


_SWING_DESCRIPTIONS = {
    "swinging_strike",
    "swinging_strike_blocked",
    "foul",
    "foul_tip",
    "foul_bunt",
    "missed_bunt",
    "hit_into_play",
}


_WHIFF_DESCRIPTIONS = {
    "swinging_strike",
    "swinging_strike_blocked",
    "missed_bunt",
}


def _rate(
    numerator,
    denominator,
):
    if not denominator:
        return None

    return (
        float(numerator)
        / float(denominator)
    )


def _mean_optional(values):
    clean = [
        float(v)
        for v in values
        if v is not None
    ]

    if not clean:
        return None

    return (
        sum(clean)
        / len(clean)
    )


def _statcast_contact_summary(
    rows,
):
    pitches = len(rows)

    swings = 0
    whiffs = 0

    bip_rows = []

    for row in rows:
        description = str(
            row.get(
                "description",
                "",
            )
        ).strip().lower()

        if (
            description
            in _SWING_DESCRIPTIONS
        ):
            swings += 1

        if (
            description
            in _WHIFF_DESCRIPTIONS
        ):
            whiffs += 1

        if (
            description
            == "hit_into_play"
        ):
            bip_rows.append(row)

    batted_types = _Counter(
        str(
            row.get(
                "bb_type",
                "",
            )
        ).strip().lower()
        for row in bip_rows
        if str(
            row.get(
                "bb_type",
                "",
            )
        ).strip()
    )

    ev_values = [
        _statcast_float(
            row.get("launch_speed")
        )
        for row in bip_rows
    ]

    ev_values = [
        x
        for x in ev_values
        if x is not None
    ]

    launch_angles = [
        _statcast_float(
            row.get("launch_angle")
        )
        for row in bip_rows
    ]

    launch_angles = [
        x
        for x in launch_angles
        if x is not None
    ]

    xba_values = [
        _statcast_float(
            row.get(
                "estimated_ba_using_speedangle"
            )
        )
        for row in bip_rows
    ]

    xwoba_values = [
        _statcast_float(
            row.get(
                "estimated_woba_using_speedangle"
            )
        )
        for row in bip_rows
    ]

    hard_hit = sum(
        1
        for x in ev_values
        if x >= 95.0
    )

    speed_angles = [
        str(
            row.get(
                "launch_speed_angle",
                "",
            )
        ).strip()
        for row in bip_rows
    ]

    barrel_like = sum(
        1
        for value in speed_angles
        if value == "6"
    )

    typed_bip = sum(
        batted_types.values()
    )

    return {
        "pitches":
            pitches,

        "swings":
            swings,

        "whiffs":
            whiffs,

        "whiff_rate_per_swing":
            _rate(
                whiffs,
                swings,
            ),

        "balls_in_play":
            len(bip_rows),

        "typed_balls_in_play":
            typed_bip,

        "ground_balls":
            batted_types.get(
                "ground_ball",
                0,
            ),

        "line_drives":
            batted_types.get(
                "line_drive",
                0,
            ),

        "fly_balls":
            batted_types.get(
                "fly_ball",
                0,
            ),

        "popups":
            batted_types.get(
                "popup",
                0,
            ),

        "gb_rate":
            _rate(
                batted_types.get(
                    "ground_ball",
                    0,
                ),
                typed_bip,
            ),

        "ld_rate":
            _rate(
                batted_types.get(
                    "line_drive",
                    0,
                ),
                typed_bip,
            ),

        "fb_rate":
            _rate(
                batted_types.get(
                    "fly_ball",
                    0,
                ),
                typed_bip,
            ),

        "popup_rate":
            _rate(
                batted_types.get(
                    "popup",
                    0,
                ),
                typed_bip,
            ),

        "avg_exit_velocity":
            _mean_optional(
                ev_values
            ),

        "avg_launch_angle":
            _mean_optional(
                launch_angles
            ),

        "hard_hit_count":
            hard_hit,

        "hard_hit_rate":
            _rate(
                hard_hit,
                len(ev_values),
            ),

        "barrel_like_count":
            barrel_like,

        "barrel_like_rate":
            _rate(
                barrel_like,
                len(speed_angles),
            ),

        "avg_xba_on_contact":
            _mean_optional(
                xba_values
            ),

        "avg_xwoba_on_contact":
            _mean_optional(
                xwoba_values
            ),
    }


def _statcast_pitch_type_profiles(
    rows,
):
    groups = {}

    for row in rows:
        pitch_type = str(
            row.get(
                "pitch_type",
                "",
            )
        ).strip()

        pitch_name = str(
            row.get(
                "pitch_name",
                "",
            )
        ).strip()

        key = (
            pitch_type
            or pitch_name
            or "UNKNOWN"
        )

        groups.setdefault(
            key,
            [],
        ).append(row)

    total = max(
        1,
        len(rows),
    )

    output = {}

    for key, group in groups.items():
        summary = (
            _statcast_contact_summary(
                group
            )
        )

        summary[
            "usage_rate"
        ] = (
            len(group)
            / total
        )

        names = [
            str(
                row.get(
                    "pitch_name",
                    "",
                )
            ).strip()
            for row in group
            if str(
                row.get(
                    "pitch_name",
                    "",
                )
            ).strip()
        ]

        summary["pitch_name"] = (
            _Counter(names)
            .most_common(1)[0][0]
            if names
            else None
        )

        output[key] = summary

    return output


def _statcast_hand_splits(
    rows,
    role,
):
    field = (
        "p_throws"
        if role == "batter"
        else "stand"
    )

    result = {}

    for hand in (
        "L",
        "R",
    ):
        subset = [
            row
            for row in rows
            if str(
                row.get(
                    field,
                    "",
                )
            ).upper()
            == hand
        ]

        if subset:
            result[hand] = (
                _statcast_contact_summary(
                    subset
                )
            )

    return result


def build_statcast_profile(
    player_name,
    role,
    season,
    start_date=None,
    end_date=None,
):
    """
    Build real Statcast pitch/contact profile.

    This is enrichment only.

    Missing Statcast data does NOT create fake values
    and does NOT automatically create a PASS.
    """

    player = find_player(
        player_name
    )

    if not player:
        raise ValueError(
            f"Player not found: {player_name}"
        )

    player_id = int(
        player["id"]
    )

    if end_date is None:
        from datetime import date

        today = date.today()

        if int(season) == today.year:
            end_date = (
                today.isoformat()
            )
        else:
            end_date = (
                f"{int(season)}-10-01"
            )

    if start_date is None:
        start_date = (
            f"{int(season)}-04-01"
        )

    try:
        downloaded = (
            _statcast_download(
                player_id,
                role,
                start_date,
                end_date,
            )
        )

        rows = downloaded[
            "rows"
        ]

        return {
            "available":
                bool(rows),

            "player_id":
                player_id,

            "player_name":
                player.get(
                    "fullName",
                    player_name,
                ),

            "role":
                role,

            "start_date":
                start_date,

            "end_date":
                end_date,

            "row_count":
                len(rows),

            "download_seconds":
                downloaded[
                    "seconds"
                ],

            "download_bytes":
                downloaded[
                    "bytes"
                ],

            "overall":
                _statcast_contact_summary(
                    rows
                ),

            "hand_splits":
                _statcast_hand_splits(
                    rows,
                    role,
                ),

            "pitch_types":
                _statcast_pitch_type_profiles(
                    rows
                ),

            "market_used":
                False,

            "source":
                downloaded[
                    "source"
                ],
        }

    except Exception as exc:
        return {
            "available":
                False,

            "player_id":
                player_id,

            "player_name":
                player.get(
                    "fullName",
                    player_name,
                ),

            "role":
                role,

            "start_date":
                start_date,

            "end_date":
                end_date,

            "row_count":
                0,

            "market_used":
                False,

            "source":
                "BASEBALL_SAVANT_STATCAST",

            "error":
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
        }


def _fmt_pct(value):
    if value is None:
        return "N/A"

    return (
        f"{100.0 * value:.1f}%"
    )


def _fmt_num(
    value,
    digits=1,
):
    if value is None:
        return "N/A"

    return (
        f"{value:.{digits}f}"
    )


def print_statcast_profile(
    profile,
):
    print()
    print("=" * 72)
    print(
        "STEP 3B — STATCAST PROFILE AUDIT"
    )
    print("=" * 72)

    print(
        "PLAYER:",
        profile.get(
            "player_name"
        ),
    )

    print(
        "ROLE:",
        profile.get("role"),
    )

    print(
        "AVAILABLE:",
        profile.get(
            "available"
        ),
    )

    print(
        "ROWS:",
        profile.get(
            "row_count"
        ),
    )

    if not profile.get(
        "available"
    ):
        print(
            "ERROR:",
            profile.get("error"),
        )
        print("=" * 72)
        return

    overall = profile[
        "overall"
    ]

    print()
    print(
        "Pitches:",
        overall["pitches"],
    )

    print(
        "Swings:",
        overall["swings"],
    )

    print(
        "Whiffs:",
        overall["whiffs"],
    )

    print(
        "Whiff/swing:",
        _fmt_pct(
            overall[
                "whiff_rate_per_swing"
            ]
        ),
    )

    print(
        "Balls in play:",
        overall[
            "balls_in_play"
        ],
    )

    print()

    print(
        "GB:",
        _fmt_pct(
            overall["gb_rate"]
        ),
    )

    print(
        "LD:",
        _fmt_pct(
            overall["ld_rate"]
        ),
    )

    print(
        "FB:",
        _fmt_pct(
            overall["fb_rate"]
        ),
    )

    print(
        "Popup:",
        _fmt_pct(
            overall["popup_rate"]
        ),
    )

    print()

    print(
        "Avg EV:",
        _fmt_num(
            overall[
                "avg_exit_velocity"
            ]
        ),
    )

    print(
        "Hard-hit:",
        _fmt_pct(
            overall[
                "hard_hit_rate"
            ]
        ),
    )

    print(
        "Barrel-like:",
        _fmt_pct(
            overall[
                "barrel_like_rate"
            ]
        ),
    )

    print(
        "xBA/contact:",
        _fmt_num(
            overall[
                "avg_xba_on_contact"
            ],
            3,
        ),
    )

    print(
        "xwOBA/contact:",
        _fmt_num(
            overall[
                "avg_xwoba_on_contact"
            ],
            3,
        ),
    )

    print()
    print(
        "TOP PITCH TYPES:"
    )

    pitch_types = sorted(
        profile[
            "pitch_types"
        ].items(),
        key=lambda item:
            item[1][
                "usage_rate"
            ],
        reverse=True,
    )

    for key, data in pitch_types[:8]:
        print(
            f"  {key:>4} "
            f"{data.get('pitch_name') or '':<18} "
            f"usage={_fmt_pct(data['usage_rate'])} "
            f"whiff={_fmt_pct(data['whiff_rate_per_swing'])} "
            f"EV={_fmt_num(data['avg_exit_velocity'])} "
            f"HH={_fmt_pct(data['hard_hit_rate'])}"
        )

    print()
    print(
        "Market used:",
        profile[
            "market_used"
        ],
    )

    print("=" * 72)




# ============================================================
# STEP 3C — PITCH ARSENAL x HITTER INTERACTION
# ============================================================

def _sample_weight(
    sample_size,
    stabilization=20.0,
):
    """
    Reliability weight for small pitch-specific samples.

    This is shrinkage, not a claim that 20 is an
    empirically optimized MLB threshold.
    """

    n = max(
        0.0,
        float(sample_size or 0),
    )

    return (
        n
        / (n + float(stabilization))
    )


def _shrink_metric(
    specific,
    baseline,
    sample_size,
    stabilization=20.0,
):
    """
    Shrink a pitch-specific statistic toward the
    player's overall Statcast profile.
    """

    if specific is None:
        return baseline

    if baseline is None:
        return specific

    weight = _sample_weight(
        sample_size,
        stabilization,
    )

    return (
        weight * specific
        + (1.0 - weight) * baseline
    )


def _canonical_pitch_name(value):
    """
    Normalize Savant pitch labels so hitter and pitcher
    pitch groups match even if formatting differs.
    """

    text = str(
        value or ""
    ).strip().lower()

    replacements = {
        "4-seam fastball":
            "four_seam",

        "four-seam fastball":
            "four_seam",

        "four seam fastball":
            "four_seam",

        "ff":
            "four_seam",

        "sinker":
            "sinker",

        "si":
            "sinker",

        "slider":
            "slider",

        "sl":
            "slider",

        "sweeper":
            "sweeper",

        "st":
            "sweeper",

        "changeup":
            "changeup",

        "ch":
            "changeup",

        "curveball":
            "curveball",

        "cu":
            "curveball",

        "knuckle curve":
            "curveball",

        "kc":
            "curveball",

        "cutter":
            "cutter",

        "fc":
            "cutter",

        "split-finger":
            "splitter",

        "splitter":
            "splitter",

        "fs":
            "splitter",

        "forkball":
            "forkball",

        "fo":
            "forkball",

        "slurve":
            "slurve",
    }

    return replacements.get(
        text,
        text.replace(
            " ",
            "_",
        ),
    )


def _canonical_pitch_profiles(
    profile,
):
    """
    Convert a Statcast profile's pitch dictionary into
    canonical pitch families.
    """

    output = {}

    for raw_key, data in (
        profile.get(
            "pitch_types",
            {}
        ).items()
    ):
        name = (
            data.get("pitch_name")
            or raw_key
        )

        key = _canonical_pitch_name(
            name
        )

        if key not in output:
            output[key] = dict(data)

        else:
            # Normally Savant already groups these.
            # If aliases collide, retain the larger sample.
            existing = output[key]

            if (
                data.get("pitches", 0)
                > existing.get(
                    "pitches",
                    0,
                )
            ):
                output[key] = dict(data)

    return output


def _pitch_metric_sample(
    data,
    metric,
):
    """
    Choose the relevant sample denominator for
    shrinkage of a pitch-specific statistic.
    """

    if metric == "whiff_rate_per_swing":
        return data.get(
            "swings",
            0,
        )

    if metric in (
        "gb_rate",
        "ld_rate",
        "fb_rate",
        "popup_rate",
    ):
        return data.get(
            "typed_balls_in_play",
            0,
        )

    if metric in (
        "avg_exit_velocity",
        "hard_hit_rate",
        "barrel_like_rate",
        "avg_xba_on_contact",
        "avg_xwoba_on_contact",
    ):
        return data.get(
            "balls_in_play",
            0,
        )

    return data.get(
        "pitches",
        0,
    )


def _shrunk_pitch_metric(
    pitch_data,
    overall,
    metric,
):
    specific = pitch_data.get(
        metric
    )

    baseline = overall.get(
        metric
    )

    sample = _pitch_metric_sample(
        pitch_data,
        metric,
    )

    stabilization = (
        25.0
        if metric
        == "whiff_rate_per_swing"
        else 18.0
    )

    return _shrink_metric(
        specific,
        baseline,
        sample,
        stabilization,
    )


def _arsenal_weighted_hitter_metric(
    hitter_statcast,
    pitcher_statcast,
    metric,
):
    """
    Estimate hitter performance against the pitcher's
    actual arsenal.

    Pitcher usage determines the weight.
    Hitter pitch-specific performance supplies the metric.
    Small hitter samples are shrunk toward hitter overall.
    """

    hitter_pitches = (
        _canonical_pitch_profiles(
            hitter_statcast
        )
    )

    pitcher_pitches = (
        _canonical_pitch_profiles(
            pitcher_statcast
        )
    )

    hitter_overall = (
        hitter_statcast.get(
            "overall",
            {}
        )
    )

    weighted = 0.0
    used_weight = 0.0
    audit = []

    for pitch, p_data in (
        pitcher_pitches.items()
    ):
        usage = p_data.get(
            "usage_rate"
        )

        if usage is None:
            continue

        h_data = hitter_pitches.get(
            pitch
        )

        if h_data:
            value = (
                _shrunk_pitch_metric(
                    h_data,
                    hitter_overall,
                    metric,
                )
            )

            sample = (
                _pitch_metric_sample(
                    h_data,
                    metric,
                )
            )

            source = (
                "HITTER_PITCH_SPECIFIC"
            )

        else:
            value = (
                hitter_overall.get(
                    metric
                )
            )

            sample = 0
            source = (
                "HITTER_OVERALL_FALLBACK"
            )

        if value is None:
            continue

        weighted += (
            float(usage)
            * float(value)
        )

        used_weight += float(
            usage
        )

        audit.append({
            "pitch":
                pitch,

            "usage":
                float(usage),

            "value":
                float(value),

            "sample":
                sample,

            "source":
                source,
        })

    if used_weight <= 0:
        return {
            "value":
                hitter_overall.get(
                    metric
                ),

            "coverage":
                0.0,

            "audit":
                audit,
        }

    return {
        "value":
            weighted / used_weight,

        "coverage":
            min(
                1.0,
                used_weight,
            ),

        "audit":
            audit,
    }


def _pitcher_allowed_metric(
    pitcher_statcast,
    metric,
):
    return (
        pitcher_statcast
        .get(
            "overall",
            {}
        )
        .get(metric)
    )


def _combine_contact_metric(
    hitter_arsenal_value,
    pitcher_allowed_value,
):
    """
    Combine hitter contact tendency with what the
    pitcher has allowed.

    Equal weighting is intentionally provisional.
    Calibration/backtesting later learns whether this
    should change.
    """

    available = [
        value
        for value in (
            hitter_arsenal_value,
            pitcher_allowed_value,
        )
        if value is not None
    ]

    if not available:
        return None

    return (
        sum(available)
        / len(available)
    )


def _normalize_contact_distribution(
    gb,
    ld,
    fb,
    popup,
):
    values = {
        "ground_ball":
            max(0.0, gb or 0.0),

        "line_drive":
            max(0.0, ld or 0.0),

        "fly_ball":
            max(0.0, fb or 0.0),

        "popup":
            max(0.0, popup or 0.0),
    }

    total = sum(
        values.values()
    )

    if total <= 0:
        return {
            key: None
            for key in values
        }

    return {
        key:
            value / total
        for key, value
        in values.items()
    }


def arsenal_matchup_interaction(
    hitter_name,
    pitcher_name,
    season,
    start_date=None,
    end_date=None,
):
    """
    Step 3C.

    Baseball-only matchup layer.

    Uses:
    - Step 2 PA probabilities
    - hitter Statcast profile
    - pitcher Statcast profile
    - pitcher's actual arsenal usage
    - hitter performance by pitch family
    - pitcher contact allowed

    Does NOT use:
    - PrizePicks line
    - market odds
    - sportsbook consensus
    """

    base = hitter_pitcher_interaction(
        hitter_name,
        pitcher_name,
        season,
    )

    hitter_sc = build_statcast_profile(
        hitter_name,
        "batter",
        season,
        start_date=start_date,
        end_date=end_date,
    )

    pitcher_sc = build_statcast_profile(
        pitcher_name,
        "pitcher",
        season,
        start_date=start_date,
        end_date=end_date,
    )

    if (
        not hitter_sc.get(
            "available"
        )
        or not pitcher_sc.get(
            "available"
        )
    ):
        return {
            "available":
                False,

            "base_interaction":
                base,

            "hitter_statcast":
                hitter_sc,

            "pitcher_statcast":
                pitcher_sc,

            "market_used":
                False,

            "prediction_created":
                False,

            "error":
                "STATCAST MATCHUP DATA UNAVAILABLE",
        }

    # --------------------------------------------------------
    # ARSENAL-WEIGHTED HITTER WHIFF
    # --------------------------------------------------------

    hitter_whiff = (
        _arsenal_weighted_hitter_metric(
            hitter_sc,
            pitcher_sc,
            "whiff_rate_per_swing",
        )
    )

    hitter_overall_whiff = (
        hitter_sc[
            "overall"
        ].get(
            "whiff_rate_per_swing"
        )
    )

    pitcher_whiff = (
        pitcher_sc[
            "overall"
        ].get(
            "whiff_rate_per_swing"
        )
    )

    # --------------------------------------------------------
    # K ADJUSTMENT
    #
    # Step 2 K probability remains the anchor.
    # Arsenal information modifies it rather than replacing it.
    # --------------------------------------------------------

    base_k = (
        base[
            "plate_appearance"
        ][
            "strikeout"
        ]
    )

    matchup_whiff = (
        _combine_contact_metric(
            hitter_whiff[
                "value"
            ],
            pitcher_whiff,
        )
    )

    neutral_whiff = (
        _combine_contact_metric(
            hitter_overall_whiff,
            pitcher_whiff,
        )
    )

    k_multiplier = 1.0

    if (
        matchup_whiff is not None
        and neutral_whiff
        and neutral_whiff > 0
    ):
        raw_ratio = (
            matchup_whiff
            / neutral_whiff
        )

        # Keep Step 3C from overpowering the established
        # PA-level K model before calibration.
        k_multiplier = _clamp(
            raw_ratio,
            0.82,
            1.18,
        )

    adjusted_k = _clamp(
        base_k * k_multiplier,
        0.03,
        0.55,
    )

    # Keep BB/HBP from Step 2.
    bb = (
        base[
            "plate_appearance"
        ]["walk"]
    )

    hbp = (
        base[
            "plate_appearance"
        ]["hit_by_pitch"]
    )

    adjusted_pa = (
        _normalize_primary_pa_outcomes(
            adjusted_k,
            bb,
            hbp,
        )
    )

    # --------------------------------------------------------
    # CONTACT SHAPE
    # --------------------------------------------------------

    contact_metrics = {}

    for metric in (
        "gb_rate",
        "ld_rate",
        "fb_rate",
        "popup_rate",
    ):
        hitter_metric = (
            _arsenal_weighted_hitter_metric(
                hitter_sc,
                pitcher_sc,
                metric,
            )
        )

        pitcher_metric = (
            _pitcher_allowed_metric(
                pitcher_sc,
                metric,
            )
        )

        contact_metrics[
            metric
        ] = {
            "hitter_arsenal":
                hitter_metric[
                    "value"
                ],

            "pitcher_allowed":
                pitcher_metric,

            "combined":
                _combine_contact_metric(
                    hitter_metric[
                        "value"
                    ],
                    pitcher_metric,
                ),
        }

    distribution = (
        _normalize_contact_distribution(
            contact_metrics[
                "gb_rate"
            ]["combined"],

            contact_metrics[
                "ld_rate"
            ]["combined"],

            contact_metrics[
                "fb_rate"
            ]["combined"],

            contact_metrics[
                "popup_rate"
            ]["combined"],
        )
    )

    # --------------------------------------------------------
    # CONTACT QUALITY
    # --------------------------------------------------------

    quality = {}

    for metric in (
        "avg_exit_velocity",
        "hard_hit_rate",
        "barrel_like_rate",
        "avg_xba_on_contact",
        "avg_xwoba_on_contact",
    ):
        hitter_metric = (
            _arsenal_weighted_hitter_metric(
                hitter_sc,
                pitcher_sc,
                metric,
            )
        )

        pitcher_metric = (
            _pitcher_allowed_metric(
                pitcher_sc,
                metric,
            )
        )

        quality[metric] = (
            _combine_contact_metric(
                hitter_metric[
                    "value"
                ],
                pitcher_metric,
            )
        )

    return {
        "available":
            True,

        "hitter":
            base["hitter"],

        "pitcher":
            base["pitcher"],

        "base_pa":
            base[
                "plate_appearance"
            ],

        "adjusted_pa":
            adjusted_pa,

        "base_k_probability":
            base_k,

        "arsenal_adjusted_k_probability":
            adjusted_k,

        "k_multiplier":
            k_multiplier,

        "hitter_overall_whiff":
            hitter_overall_whiff,

        "hitter_arsenal_whiff":
            hitter_whiff[
                "value"
            ],

        "pitcher_whiff":
            pitcher_whiff,

        "matchup_whiff":
            matchup_whiff,

        "arsenal_coverage":
            hitter_whiff[
                "coverage"
            ],

        "pitch_audit":
            hitter_whiff[
                "audit"
            ],

        "contact_distribution":
            distribution,

        "contact_quality":
            quality,

        "market_used":
            False,

        "prediction_created":
            False,

        "recommendation_created":
            False,
    }


def print_arsenal_matchup_audit(
    result,
):
    print()
    print("=" * 72)
    print(
        "STEP 3C — ARSENAL MATCHUP AUDIT"
    )
    print("=" * 72)

    if not result.get(
        "available"
    ):
        print(
            "AVAILABLE: False"
        )
        print(
            result.get(
                "error"
            )
        )
        print("=" * 72)
        return

    h = result["hitter"]
    p = result["pitcher"]

    print(
        f"{h['name']} "
        f"({h.get('bat_side') or '?'})"
    )

    print("vs")

    print(
        f"{p['name']} "
        f"({p.get('pitch_hand') or '?'})"
    )

    print()

    print(
        "Step 2 P(K):",
        _fmt_pct(
            result[
                "base_k_probability"
            ]
        ),
    )

    print(
        "Arsenal P(K):",
        _fmt_pct(
            result[
                "arsenal_adjusted_k_probability"
            ]
        ),
    )

    print(
        "K multiplier:",
        _fmt_num(
            result[
                "k_multiplier"
            ],
            3,
        ),
    )

    print()

    print(
        "Hitter overall whiff:",
        _fmt_pct(
            result[
                "hitter_overall_whiff"
            ]
        ),
    )

    print(
        "Hitter vs pitcher arsenal:",
        _fmt_pct(
            result[
                "hitter_arsenal_whiff"
            ]
        ),
    )

    print(
        "Pitcher whiff:",
        _fmt_pct(
            result[
                "pitcher_whiff"
            ]
        ),
    )

    print(
        "Combined matchup whiff:",
        _fmt_pct(
            result[
                "matchup_whiff"
            ]
        ),
    )

    print()

    print(
        "PITCH-BY-PITCH HITTER AUDIT:"
    )

    audit = sorted(
        result[
            "pitch_audit"
        ],
        key=lambda row:
            row["usage"],
        reverse=True,
    )

    for row in audit:
        print(
            f"  {row['pitch']:<12} "
            f"usage={_fmt_pct(row['usage'])} "
            f"hitter_whiff={_fmt_pct(row['value'])} "
            f"sample={row['sample']} "
            f"{row['source']}"
        )

    print()
    print(
        "CONTACT IF BALL IS PUT IN PLAY:"
    )

    contact = result[
        "contact_distribution"
    ]

    print(
        "  GB:",
        _fmt_pct(
            contact[
                "ground_ball"
            ]
        ),
    )

    print(
        "  LD:",
        _fmt_pct(
            contact[
                "line_drive"
            ]
        ),
    )

    print(
        "  FB:",
        _fmt_pct(
            contact[
                "fly_ball"
            ]
        ),
    )

    print(
        "  Popup:",
        _fmt_pct(
            contact[
                "popup"
            ]
        ),
    )

    print()
    print(
        "CONTACT QUALITY:"
    )

    quality = result[
        "contact_quality"
    ]

    print(
        "  Expected EV:",
        _fmt_num(
            quality[
                "avg_exit_velocity"
            ]
        ),
    )

    print(
        "  Hard-hit:",
        _fmt_pct(
            quality[
                "hard_hit_rate"
            ]
        ),
    )

    print(
        "  Barrel-like:",
        _fmt_pct(
            quality[
                "barrel_like_rate"
            ]
        ),
    )

    print(
        "  xBA/contact:",
        _fmt_num(
            quality[
                "avg_xba_on_contact"
            ],
            3,
        ),
    )

    print(
        "  xwOBA/contact:",
        _fmt_num(
            quality[
                "avg_xwoba_on_contact"
            ],
            3,
        ),
    )

    print()

    pa = result[
        "adjusted_pa"
    ]

    print(
        "FINAL STEP-3C PA:"
    )

    print(
        "  K:",
        _fmt_pct(
            pa["strikeout"]
        ),
    )

    print(
        "  BB:",
        _fmt_pct(
            pa["walk"]
        ),
    )

    print(
        "  HBP:",
        _fmt_pct(
            pa["hit_by_pitch"]
        ),
    )

    print(
        "  BIP/other:",
        _fmt_pct(
            pa[
                "ball_in_play_or_other"
            ]
        ),
    )

    print(
        "  Total:",
        f"{sum(pa.values()):.6f}",
    )

    print()

    print(
        "Market used:",
        result[
            "market_used"
        ],
    )

    print(
        "PrizePicks prediction:",
        result[
            "prediction_created"
        ],
    )

    print(
        "Recommendation:",
        result[
            "recommendation_created"
        ],
    )

    print("=" * 72)




# ============================================================
# STEP 4 — CONTACT -> BATTING OUTCOME DISTRIBUTION
# ============================================================

def _normalize_probability_dict(values):
    clean = {
        key: max(
            0.0,
            float(value or 0.0),
        )
        for key, value
        in values.items()
    }

    total = sum(clean.values())

    if total <= 0:
        return {
            key: None
            for key in clean
        }

    return {
        key: value / total
        for key, value
        in clean.items()
    }


def _event_counts_from_hitter_games(
    player_name,
    season,
):
    """
    Build season batting-event counts from the verified
    MLB game logs already used by the profile layer.

    These become the anchor for Step 4.

    We do NOT infer exact hit types from xBA/xwOBA.
    """

    player = find_player(
        player_name
    )

    if not player:
        raise ValueError(
            f"Player not found: {player_name}"
        )

    games = player_game_log(
        int(player["id"]),
        int(season),
        "hitting",
    )

    counts = {
        "pa": 0.0,
        "ab": 0.0,
        "strikeouts": 0.0,
        "walks": 0.0,
        "hbp": 0.0,
        "singles": 0.0,
        "doubles": 0.0,
        "triples": 0.0,
        "home_runs": 0.0,
        "hits": 0.0,
    }

    for game in games:
        s = (
            game.get("stat")
            or {}
        )

        pa = _statcast_float(
            s.get(
                "plateAppearances"
            )
        )

        ab = _statcast_float(
            s.get("atBats")
        ) or 0.0

        bb = _statcast_float(
            s.get("baseOnBalls")
        ) or 0.0

        hbp = _statcast_float(
            s.get("hitByPitch")
        ) or 0.0

        sf = _statcast_float(
            s.get("sacFlies")
        ) or 0.0

        sh = _statcast_float(
            s.get("sacBunts")
        ) or 0.0

        if pa is None:
            pa = (
                ab
                + bb
                + hbp
                + sf
                + sh
            )

        hits = _statcast_float(
            s.get("hits")
        ) or 0.0

        doubles = _statcast_float(
            s.get("doubles")
        ) or 0.0

        triples = _statcast_float(
            s.get("triples")
        ) or 0.0

        hr = _statcast_float(
            s.get("homeRuns")
        ) or 0.0

        singles = max(
            0.0,
            hits
            - doubles
            - triples
            - hr,
        )

        counts["pa"] += pa
        counts["ab"] += ab

        counts["strikeouts"] += (
            _statcast_float(
                s.get("strikeOuts")
            )
            or 0.0
        )

        counts["walks"] += bb
        counts["hbp"] += hbp

        counts["singles"] += singles
        counts["doubles"] += doubles
        counts["triples"] += triples
        counts["home_runs"] += hr
        counts["hits"] += hits

    return counts


def _season_contact_outcomes(
    player_name,
    season,
):
    """
    Conditional distribution after removing K / BB / HBP.

    This is not claiming every remaining PA is a Statcast
    ball in play. It is our event-tree branch for outcomes
    that can produce OUT / 1B / 2B / 3B / HR.

    Sacrifice events and other non-hit results remain in OUT.
    """

    c = _event_counts_from_hitter_games(
        player_name,
        season,
    )

    branch_pa = max(
        0.0,
        c["pa"]
        - c["strikeouts"]
        - c["walks"]
        - c["hbp"],
    )

    hits = (
        c["singles"]
        + c["doubles"]
        + c["triples"]
        + c["home_runs"]
    )

    outs = max(
        0.0,
        branch_pa - hits,
    )

    distribution = (
        _normalize_probability_dict({
            "out": outs,
            "single":
                c["singles"],
            "double":
                c["doubles"],
            "triple":
                c["triples"],
            "home_run":
                c["home_runs"],
        })
    )

    return {
        "counts": c,
        "branch_pa": branch_pa,
        "distribution":
            distribution,
    }


def _quality_ratio(
    matchup_value,
    hitter_baseline,
    low,
    high,
):
    """
    Conservative relative contact-quality signal.

    A ratio above 1 means matchup contact quality looks
    better than the hitter baseline; below 1 means worse.

    Hard caps prevent small Statcast samples from creating
    extreme event probabilities.
    """

    if (
        matchup_value is None
        or hitter_baseline is None
        or hitter_baseline <= 0
    ):
        return 1.0

    return _clamp(
        matchup_value
        / hitter_baseline,
        low,
        high,
    )


def _adjust_contact_outcomes(
    season_distribution,
    hitter_statcast,
    arsenal_result,
):
    """
    Apply deliberately small Statcast adjustments to the
    season event distribution.

    Season outcomes remain the anchor.

    Signals:
    - xBA/contact affects total hit likelihood slightly.
    - hard-hit affects extra-base damage slightly.
    - barrel-like affects HR likelihood slightly.
    - GB/LD/FB shape provides a small structural nudge.

    This is intentionally conservative until backtesting.
    """

    base = dict(
        season_distribution
    )

    overall = (
        hitter_statcast.get(
            "overall",
            {}
        )
    )

    quality = (
        arsenal_result.get(
            "contact_quality",
            {}
        )
    )

    shape = (
        arsenal_result.get(
            "contact_distribution",
            {}
        )
    )

    xba_ratio = _quality_ratio(
        quality.get(
            "avg_xba_on_contact"
        ),
        overall.get(
            "avg_xba_on_contact"
        ),
        0.88,
        1.12,
    )

    hard_ratio = _quality_ratio(
        quality.get(
            "hard_hit_rate"
        ),
        overall.get(
            "hard_hit_rate"
        ),
        0.88,
        1.12,
    )

    barrel_ratio = _quality_ratio(
        quality.get(
            "barrel_like_rate"
        ),
        overall.get(
            "barrel_like_rate"
        ),
        0.85,
        1.15,
    )

    base_gb = overall.get(
        "gb_rate"
    )

    base_ld = overall.get(
        "ld_rate"
    )

    base_fb = overall.get(
        "fb_rate"
    )

    matchup_gb = shape.get(
        "ground_ball"
    )

    matchup_ld = shape.get(
        "line_drive"
    )

    matchup_fb = shape.get(
        "fly_ball"
    )

    ld_ratio = _quality_ratio(
        matchup_ld,
        base_ld,
        0.90,
        1.10,
    )

    fb_ratio = _quality_ratio(
        matchup_fb,
        base_fb,
        0.90,
        1.10,
    )

    gb_ratio = _quality_ratio(
        matchup_gb,
        base_gb,
        0.90,
        1.10,
    )

    # --------------------------------------------------------
    # LIMITED ADJUSTMENTS
    # --------------------------------------------------------

    single_mult = (
        1.0
        + 0.30 * (
            xba_ratio - 1.0
        )
        + 0.08 * (
            ld_ratio - 1.0
        )
        - 0.04 * (
            gb_ratio - 1.0
        )
    )

    double_mult = (
        1.0
        + 0.20 * (
            xba_ratio - 1.0
        )
        + 0.22 * (
            hard_ratio - 1.0
        )
        + 0.10 * (
            ld_ratio - 1.0
        )
    )

    triple_mult = (
        1.0
        + 0.10 * (
            xba_ratio - 1.0
        )
        + 0.08 * (
            hard_ratio - 1.0
        )
    )

    hr_mult = (
        1.0
        + 0.16 * (
            hard_ratio - 1.0
        )
        + 0.22 * (
            barrel_ratio - 1.0
        )
        + 0.08 * (
            fb_ratio - 1.0
        )
    )

    # Extremely small event categories such as triples
    # must never explode because of one contact signal.
    single_mult = _clamp(
        single_mult,
        0.92,
        1.08,
    )

    double_mult = _clamp(
        double_mult,
        0.90,
        1.10,
    )

    triple_mult = _clamp(
        triple_mult,
        0.94,
        1.06,
    )

    hr_mult = _clamp(
        hr_mult,
        0.88,
        1.12,
    )

    adjusted_hits = {
        "single":
            base["single"]
            * single_mult,

        "double":
            base["double"]
            * double_mult,

        "triple":
            base["triple"]
            * triple_mult,

        "home_run":
            base["home_run"]
            * hr_mult,
    }

    base_hit_probability = (
        base["single"]
        + base["double"]
        + base["triple"]
        + base["home_run"]
    )

    # Overall xBA/contact is allowed to move total hit
    # probability only slightly.
    target_hit_probability = _clamp(
        base_hit_probability
        * (
            1.0
            + 0.20
            * (xba_ratio - 1.0)
        ),
        max(
            0.01,
            base_hit_probability
            * 0.94,
        ),
        min(
            0.95,
            base_hit_probability
            * 1.06,
        ),
    )

    raw_hit_total = sum(
        adjusted_hits.values()
    )

    if raw_hit_total > 0:
        scale = (
            target_hit_probability
            / raw_hit_total
        )

        adjusted_hits = {
            key:
                value * scale
            for key, value
            in adjusted_hits.items()
        }

    adjusted = {
        "out":
            max(
                0.0,
                1.0
                - sum(
                    adjusted_hits.values()
                ),
            ),

        **adjusted_hits,
    }

    adjusted = (
        _normalize_probability_dict(
            adjusted
        )
    )

    return {
        "distribution":
            adjusted,

        "multipliers": {
            "single":
                single_mult,

            "double":
                double_mult,

            "triple":
                triple_mult,

            "home_run":
                hr_mult,
        },

        "signals": {
            "xba_ratio":
                xba_ratio,

            "hard_hit_ratio":
                hard_ratio,

            "barrel_ratio":
                barrel_ratio,

            "gb_ratio":
                gb_ratio,

            "ld_ratio":
                ld_ratio,

            "fb_ratio":
                fb_ratio,
        },

        "base_hit_probability":
            base_hit_probability,

        "adjusted_hit_probability":
            (
                adjusted["single"]
                + adjusted["double"]
                + adjusted["triple"]
                + adjusted["home_run"]
            ),
    }


def batting_outcome_interaction(
    hitter_name,
    pitcher_name,
    season,
    start_date=None,
    end_date=None,
):
    """
    Step 4 baseball event tree.

    Produces:
    PA:
      K / BB / HBP / CONTACT BRANCH

    Conditional contact branch:
      OUT / 1B / 2B / 3B / HR

    No PrizePicks line.
    No market.
    No MORE/LESS recommendation.
    """

    arsenal = (
        arsenal_matchup_interaction(
            hitter_name,
            pitcher_name,
            season,
            start_date=start_date,
            end_date=end_date,
        )
    )

    if not arsenal.get(
        "available"
    ):
        return {
            "available":
                False,

            "arsenal":
                arsenal,

            "market_used":
                False,

            "prediction_created":
                False,

            "recommendation_created":
                False,
        }

    season_events = (
        _season_contact_outcomes(
            hitter_name,
            season,
        )
    )

    hitter_sc = (
        build_statcast_profile(
            hitter_name,
            "batter",
            season,
            start_date=start_date,
            end_date=end_date,
        )
    )

    adjusted = (
        _adjust_contact_outcomes(
            season_events[
                "distribution"
            ],
            hitter_sc,
            arsenal,
        )
    )

    pa = arsenal[
        "adjusted_pa"
    ]

    contact_probability = pa[
        "ball_in_play_or_other"
    ]

    conditional = adjusted[
        "distribution"
    ]

    # --------------------------------------------------------
    # UNCONDITIONAL PER-PA EVENT PROBABILITIES
    # --------------------------------------------------------

    per_pa = {
        "strikeout":
            pa["strikeout"],

        "walk":
            pa["walk"],

        "hit_by_pitch":
            pa["hit_by_pitch"],

        "out_on_contact":
            contact_probability
            * conditional["out"],

        "single":
            contact_probability
            * conditional["single"],

        "double":
            contact_probability
            * conditional["double"],

        "triple":
            contact_probability
            * conditional["triple"],

        "home_run":
            contact_probability
            * conditional["home_run"],
    }

    total = sum(
        per_pa.values()
    )

    # Numerical safety only.
    if total > 0:
        per_pa = {
            key:
                value / total
            for key, value
            in per_pa.items()
        }

    hit_probability_per_pa = (
        per_pa["single"]
        + per_pa["double"]
        + per_pa["triple"]
        + per_pa["home_run"]
    )

    total_base_expectation_per_pa = (
        per_pa["single"]
        + 2.0 * per_pa["double"]
        + 3.0 * per_pa["triple"]
        + 4.0 * per_pa["home_run"]
    )

    return {
        "available":
            True,

        "hitter":
            arsenal["hitter"],

        "pitcher":
            arsenal["pitcher"],

        "pa":
            pa,

        "season_contact_distribution":
            season_events[
                "distribution"
            ],

        "matchup_contact_distribution":
            conditional,

        "contact_adjustment":
            adjusted,

        "per_pa_events":
            per_pa,

        "hit_probability_per_pa":
            hit_probability_per_pa,

        "total_base_expectation_per_pa":
            total_base_expectation_per_pa,

        "market_used":
            False,

        "prediction_created":
            False,

        "recommendation_created":
            False,
    }


def print_batting_outcome_audit(
    result,
):
    print()
    print("=" * 72)
    print(
        "STEP 4 — BATTING OUTCOME AUDIT"
    )
    print("=" * 72)

    if not result.get(
        "available"
    ):
        print(
            "AVAILABLE: False"
        )
        print("=" * 72)
        return

    h = result["hitter"]
    p = result["pitcher"]

    print(
        f"{h['name']} "
        f"({h.get('bat_side') or '?'})"
    )

    print("vs")

    print(
        f"{p['name']} "
        f"({p.get('pitch_hand') or '?'})"
    )

    print()

    print(
        "SEASON CONTACT BRANCH:"
    )

    for key, value in (
        result[
            "season_contact_distribution"
        ].items()
    ):
        print(
            f"  {key:<10}",
            _fmt_pct(value),
        )

    print()

    print(
        "MATCHUP CONTACT BRANCH:"
    )

    for key, value in (
        result[
            "matchup_contact_distribution"
        ].items()
    ):
        print(
            f"  {key:<10}",
            _fmt_pct(value),
        )

    print()

    adjustment = result[
        "contact_adjustment"
    ]

    print(
        "CONTACT SIGNALS:"
    )

    for key, value in (
        adjustment[
            "signals"
        ].items()
    ):
        print(
            f"  {key:<18}",
            _fmt_num(
                value,
                3,
            ),
        )

    print()

    print(
        "EVENT MULTIPLIERS:"
    )

    for key, value in (
        adjustment[
            "multipliers"
        ].items()
    ):
        print(
            f"  {key:<10}",
            _fmt_num(
                value,
                3,
            ),
        )

    print()

    print(
        "FINAL PER-PA EVENT TREE:"
    )

    for key, value in (
        result[
            "per_pa_events"
        ].items()
    ):
        print(
            f"  {key:<15}",
            _fmt_pct(value),
        )

    print()

    print(
        "Hit probability / PA:",
        _fmt_pct(
            result[
                "hit_probability_per_pa"
            ]
        ),
    )

    print(
        "Expected TB / PA:",
        _fmt_num(
            result[
                "total_base_expectation_per_pa"
            ],
            3,
        ),
    )

    print(
        "PA event total:",
        f"{sum(result['per_pa_events'].values()):.6f}",
    )

    print()

    print(
        "Market used:",
        result[
            "market_used"
        ],
    )

    print(
        "Prediction:",
        result[
            "prediction_created"
        ],
    )

    print(
        "Recommendation:",
        result[
            "recommendation_created"
        ],
    )

    print("=" * 72)




# ============================================================
# STEPS 5-8 BUNDLE
#
# STEP 5 — BASERUNNING / STOLEN BASES
# STEP 6 — OPPORTUNITY / WORKLOAD
# STEP 7 — STARTER -> BULLPEN TRANSITION
# STEP 8 — PARK / WEATHER CONTEXT
# ============================================================


def _bounded(value, low, high):
    if value is None:
        return None

    return max(
        low,
        min(
            high,
            float(value),
        ),
    )


# ============================================================
# STEP 5 — BASERUNNING / STOLEN BASES
# ============================================================

def _runner_reach_probability(
    event_tree,
):
    """
    Probability the hitter reaches safely in a PA through
    events that can create a stolen-base opportunity.

    HR is excluded because a HR does not create an SB
    opportunity.

    HBP and BB are included.
    """

    events = (
        event_tree.get(
            "per_pa_events",
            {}
        )
    )

    return (
        events.get("walk", 0.0)
        + events.get(
            "hit_by_pitch",
            0.0,
        )
        + events.get(
            "single",
            0.0,
        )
        + events.get(
            "double",
            0.0,
        )
        + events.get(
            "triple",
            0.0,
        )
    )


def baserunning_profile(
    hitter_name,
    pitcher_name,
    season,
    event_tree,
):
    """
    Conservative stolen-base model.

    Structure:

    P(SB per PA)
      =
    P(reach eligible base)
      x
    P(attempt | reach)
      x
    P(success | attempt)

    Runner history is the anchor.

    Pitcher/catcher hold effects are NOT invented when
    verified data is unavailable.
    """

    hitter = build_hitter_profile(
        hitter_name,
        season,
    )

    reach_probability = (
        _runner_reach_probability(
            event_tree
        )
    )

    attempt_rate = hitter.get(
        "sb_attempt_rate_per_reach"
    )

    success_rate = hitter.get(
        "sb_success_rate"
    )

    if attempt_rate is None:
        attempt_rate = 0.0

    if success_rate is None:
        success_rate = 0.0

    attempt_rate = _bounded(
        attempt_rate,
        0.0,
        0.65,
    )

    success_rate = _bounded(
        success_rate,
        0.0,
        1.0,
    )

    sb_per_pa = (
        reach_probability
        * attempt_rate
        * success_rate
    )

    return {
        "reach_probability_per_pa":
            reach_probability,

        "attempt_rate_given_reach":
            attempt_rate,

        "success_rate_given_attempt":
            success_rate,

        "stolen_base_probability_per_pa":
            sb_per_pa,

        "pitcher_hold_adjustment":
            1.0,

        "catcher_adjustment":
            1.0,

        "verified_hold_data":
            False,

        "verified_catcher_data":
            False,

        "market_used":
            False,

        "note": (
            "Runner history used as anchor; "
            "pitcher/catcher run-control effects remain "
            "neutral until verified data is available."
        ),
    }


# ============================================================
# STEP 6 — OPPORTUNITY / WORKLOAD
# ============================================================

def _expected_hitter_pa_from_profile(
    hitter_name,
    season,
    batting_order=None,
):
    """
    Estimate expected PA from recent actual PA.

    Batting order changes opportunity only.
    It does not determine whether a prop can cash.
    """

    player = find_player(
        hitter_name
    )

    if not player:
        return None

    games = player_game_log(
        int(player["id"]),
        int(season),
        "hitting",
    )

    recent = []

    for game in games[-20:]:
        stat = (
            game.get("stat")
            or {}
        )

        pa = _statcast_float(
            stat.get(
                "plateAppearances"
            )
        )

        if pa is None:
            pa = (
                (_statcast_float(
                    stat.get("atBats")
                ) or 0.0)
                + (_statcast_float(
                    stat.get("baseOnBalls")
                ) or 0.0)
                + (_statcast_float(
                    stat.get("hitByPitch")
                ) or 0.0)
                + (_statcast_float(
                    stat.get("sacFlies")
                ) or 0.0)
                + (_statcast_float(
                    stat.get("sacBunts")
                ) or 0.0)
            )

        if pa > 0:
            recent.append(pa)

    if not recent:
        return None

    baseline = _mean_optional(
        recent
    )

    multiplier = {
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
        batting_order,
        1.0,
    )

    expected = (
        baseline
        * multiplier
    )

    return _bounded(
        expected,
        2.5,
        5.5,
    )


def _expected_pitcher_workload(
    pitcher_name,
    season,
):
    """
    Expected starter workload from recent verified MLB
    game logs.

    Returns expected outs, batters faced and pitches when
    available.

    Missing fields remain missing.
    """

    player = find_player(
        pitcher_name
    )

    if not player:
        return {
            "expected_outs":
                None,

            "expected_batters_faced":
                None,

            "expected_pitches":
                None,
        }

    games = player_game_log(
        int(player["id"]),
        int(season),
        "pitching",
    )

    outs_values = []
    bf_values = []
    pitch_values = []

    for game in games[-10:]:
        stat = (
            game.get("stat")
            or {}
        )

        ip = str(
            stat.get(
                "inningsPitched",
                "0.0",
            )
        )

        try:
            whole, fraction = (
                ip.split(".")
            )

            outs = (
                int(whole) * 3
                + int(fraction)
            )

        except Exception:
            outs = None

        if (
            outs is not None
            and outs >= 0
        ):
            outs_values.append(
                float(outs)
            )

        bf = _statcast_float(
            stat.get(
                "battersFaced"
            )
        )

        if (
            bf is not None
            and bf > 0
        ):
            bf_values.append(bf)

        pitches = _statcast_float(
            stat.get(
                "numberOfPitches"
            )
        )

        if pitches is None:
            pitches = _statcast_float(
                stat.get(
                    "pitchesThrown"
                )
            )

        if (
            pitches is not None
            and pitches > 0
        ):
            pitch_values.append(
                pitches
            )

    return {
        "expected_outs":
            _mean_optional(
                outs_values
            ),

        "expected_batters_faced":
            _mean_optional(
                bf_values
            ),

        "expected_pitches":
            _mean_optional(
                pitch_values
            ),

        "sample_games":
            min(
                10,
                len(games),
            ),
    }


def opportunity_context(
    hitter_name,
    pitcher_name,
    season,
    batting_order=None,
):
    expected_pa = (
        _expected_hitter_pa_from_profile(
            hitter_name,
            season,
            batting_order,
        )
    )

    pitcher_workload = (
        _expected_pitcher_workload(
            pitcher_name,
            season,
        )
    )

    return {
        "batting_order":
            batting_order,

        "expected_plate_appearances":
            expected_pa,

        "pitcher_workload":
            pitcher_workload,

        "market_used":
            False,
    }


# ============================================================
# STEP 7 — STARTER -> BULLPEN TRANSITION
# ============================================================

def _starter_exposure_probability(
    expected_pa,
    expected_batters_faced,
):
    """
    Approximate fraction of hitter PAs expected to occur
    against the starting pitcher.

    This does NOT pretend we know exact future batting-order
    cycles.

    Starter BF is converted into expected lineup turns.
    """

    if (
        expected_pa is None
        or expected_pa <= 0
    ):
        return None

    if (
        expected_batters_faced is None
        or expected_batters_faced <= 0
    ):
        return None

    lineup_turns = (
        expected_batters_faced
        / 9.0
    )

    starter_pa = _bounded(
        lineup_turns,
        0.0,
        expected_pa,
    )

    return _bounded(
        starter_pa
        / expected_pa,
        0.0,
        1.0,
    )


def _hitter_season_event_tree(
    hitter_name,
    season,
):
    """
    Neutral hitter event tree used as a fallback for
    bullpen-facing plate appearances.

    We do NOT pretend the opposing bullpen has the same
    matchup profile as the starter.

    A richer bullpen-specific model will replace this
    neutral branch when verified reliever data is supplied.
    """

    hitter = build_hitter_profile(
        hitter_name,
        season,
    )

    season_contact = (
        _season_contact_outcomes(
            hitter_name,
            season,
        )
    )

    k = hitter.get(
        "k_rate"
    ) or 0.0

    bb = hitter.get(
        "bb_rate"
    ) or 0.0

    hbp = hitter.get(
        "hbp_rate"
    ) or 0.0

    pa = (
        _normalize_primary_pa_outcomes(
            k,
            bb,
            hbp,
        )
    )

    branch = (
        season_contact[
            "distribution"
        ]
    )

    contact = pa[
        "ball_in_play_or_other"
    ]

    events = {
        "strikeout":
            pa["strikeout"],

        "walk":
            pa["walk"],

        "hit_by_pitch":
            pa["hit_by_pitch"],

        "out_on_contact":
            contact
            * branch["out"],

        "single":
            contact
            * branch["single"],

        "double":
            contact
            * branch["double"],

        "triple":
            contact
            * branch["triple"],

        "home_run":
            contact
            * branch["home_run"],
    }

    total = sum(
        events.values()
    )

    if total > 0:
        events = {
            key:
                value / total
            for key, value
            in events.items()
        }

    return events


def _blend_event_trees(
    starter_tree,
    bullpen_tree,
    starter_weight,
):
    starter_weight = _bounded(
        starter_weight,
        0.0,
        1.0,
    )

    bullpen_weight = (
        1.0 - starter_weight
    )

    keys = set(
        starter_tree
    ) | set(
        bullpen_tree
    )

    output = {}

    for key in keys:
        output[key] = (
            starter_weight
            * starter_tree.get(
                key,
                0.0,
            )
            + bullpen_weight
            * bullpen_tree.get(
                key,
                0.0,
            )
        )

    total = sum(
        output.values()
    )

    if total > 0:
        output = {
            key:
                value / total
            for key, value
            in output.items()
        }

    return output


def starter_bullpen_transition(
    hitter_name,
    season,
    starter_event_tree,
    opportunity,
):
    expected_pa = (
        opportunity.get(
            "expected_plate_appearances"
        )
    )

    workload = (
        opportunity.get(
            "pitcher_workload",
            {}
        )
    )

    expected_bf = (
        workload.get(
            "expected_batters_faced"
        )
    )

    starter_exposure = (
        _starter_exposure_probability(
            expected_pa,
            expected_bf,
        )
    )

    if starter_exposure is None:
        starter_exposure = 0.65
        exposure_source = (
            "CONSERVATIVE_FALLBACK"
        )
    else:
        exposure_source = (
            "RECENT_STARTER_BF"
        )

    # Avoid claiming 100% starter exposure even for
    # workhorse starters.
    starter_exposure = _bounded(
        starter_exposure,
        0.35,
        0.85,
    )

    bullpen_exposure = (
        1.0
        - starter_exposure
    )

    bullpen_tree = (
        _hitter_season_event_tree(
            hitter_name,
            season,
        )
    )

    blended = (
        _blend_event_trees(
            starter_event_tree,
            bullpen_tree,
            starter_exposure,
        )
    )

    return {
        "starter_exposure":
            starter_exposure,

        "bullpen_exposure":
            bullpen_exposure,

        "exposure_source":
            exposure_source,

        "starter_event_tree":
            starter_event_tree,

        "bullpen_event_tree":
            bullpen_tree,

        "blended_event_tree":
            blended,

        "bullpen_model":
            "HITTER_SEASON_NEUTRAL",

        "verified_bullpen_specific":
            False,

        "market_used":
            False,
    }


# ============================================================
# STEP 8 — PARK / WEATHER
# ============================================================

def _weather_adjustment_from_context(
    weather,
):
    """
    Conservative weather adjustment.

    Only verified structured conditions are used.

    No data -> exactly neutral.
    """

    result = {
        "hr_multiplier":
            1.0,

        "xbh_multiplier":
            1.0,

        "hit_multiplier":
            1.0,

        "verified":
            False,

        "signals": [],
    }

    if not isinstance(
        weather,
        dict,
    ):
        return result

    temp = _statcast_float(
        weather.get(
            "temp"
        )
    )

    if temp is None:
        temp = _statcast_float(
            weather.get(
                "temperature"
            )
        )

    wind = _statcast_float(
        weather.get(
            "wind_speed"
        )
    )

    wind_direction = str(
        weather.get(
            "wind_direction",
            weather.get(
                "wind",
                "",
            ),
        )
        or ""
    ).lower()

    if temp is not None:
        result["verified"] = True

        if temp >= 85:
            result[
                "hr_multiplier"
            ] *= 1.025

            result[
                "xbh_multiplier"
            ] *= 1.012

            result["signals"].append(
                "HOT_AIR"
            )

        elif temp <= 50:
            result[
                "hr_multiplier"
            ] *= 0.975

            result[
                "xbh_multiplier"
            ] *= 0.988

            result["signals"].append(
                "COLD_AIR"
            )

    if (
        wind is not None
        and wind >= 8
    ):
        result["verified"] = True

        if "out" in wind_direction:
            result[
                "hr_multiplier"
            ] *= 1.025

            result["signals"].append(
                "WIND_OUT"
            )

        elif "in" in wind_direction:
            result[
                "hr_multiplier"
            ] *= 0.975

            result["signals"].append(
                "WIND_IN"
            )

    result[
        "hr_multiplier"
    ] = _bounded(
        result[
            "hr_multiplier"
        ],
        0.94,
        1.06,
    )

    result[
        "xbh_multiplier"
    ] = _bounded(
        result[
            "xbh_multiplier"
        ],
        0.96,
        1.04,
    )

    return result


def _park_adjustment(
    park_factor=None,
):
    """
    Accept an externally verified park factor when one is
    eventually supplied.

    1.00 = neutral.

    No verified park factor -> neutral.

    We deliberately do not hard-code guessed park ratings.
    """

    if park_factor is None:
        return {
            "verified":
                False,

            "park_factor":
                1.0,

            "hr_multiplier":
                1.0,

            "xbh_multiplier":
                1.0,
        }

    factor = _bounded(
        park_factor,
        0.90,
        1.10,
    )

    return {
        "verified":
            True,

        "park_factor":
            factor,

        "hr_multiplier":
            _bounded(
                1.0
                + 0.50
                * (factor - 1.0),
                0.95,
                1.05,
            ),

        "xbh_multiplier":
            _bounded(
                1.0
                + 0.25
                * (factor - 1.0),
                0.97,
                1.03,
            ),
    }


def apply_environment_to_event_tree(
    event_tree,
    weather=None,
    park_factor=None,
):
    """
    Environment modifies only relevant contact outcomes.

    It does not apply a blanket MORE multiplier.
    """

    weather_adj = (
        _weather_adjustment_from_context(
            weather
        )
    )

    park_adj = (
        _park_adjustment(
            park_factor
        )
    )

    adjusted = dict(
        event_tree
    )

    hr_mult = (
        weather_adj[
            "hr_multiplier"
        ]
        * park_adj[
            "hr_multiplier"
        ]
    )

    xbh_mult = (
        weather_adj[
            "xbh_multiplier"
        ]
        * park_adj[
            "xbh_multiplier"
        ]
    )

    adjusted["home_run"] = (
        adjusted.get(
            "home_run",
            0.0,
        )
        * hr_mult
    )

    adjusted["double"] = (
        adjusted.get(
            "double",
            0.0,
        )
        * xbh_mult
    )

    adjusted["triple"] = (
        adjusted.get(
            "triple",
            0.0,
        )
        * xbh_mult
    )

    # Preserve non-contact PA outcomes.
    fixed = (
        adjusted.get(
            "strikeout",
            0.0,
        )
        + adjusted.get(
            "walk",
            0.0,
        )
        + adjusted.get(
            "hit_by_pitch",
            0.0,
        )
    )

    contact_keys = (
        "out_on_contact",
        "single",
        "double",
        "triple",
        "home_run",
    )

    contact_target = max(
        0.0,
        1.0 - fixed,
    )

    contact_total = sum(
        adjusted.get(
            key,
            0.0,
        )
        for key in contact_keys
    )

    if contact_total > 0:
        scale = (
            contact_target
            / contact_total
        )

        for key in contact_keys:
            adjusted[key] = (
                adjusted.get(
                    key,
                    0.0,
                )
                * scale
            )

    return {
        "event_tree":
            adjusted,

        "weather":
            weather_adj,

        "park":
            park_adj,

        "market_used":
            False,
    }


# ============================================================
# COMBINED STEP 5-8 MATCHUP CONTEXT
# ============================================================

def matchup_context_v2(
    hitter_name,
    pitcher_name,
    season,
    batting_order=None,
    weather=None,
    park_factor=None,
    start_date=None,
    end_date=None,
):
    """
    Combined V2 baseball context through Step 8.

    Still no PrizePicks line and no market.
    """

    batting = (
        batting_outcome_interaction(
            hitter_name,
            pitcher_name,
            season,
            start_date=start_date,
            end_date=end_date,
        )
    )

    if not batting.get(
        "available"
    ):
        return {
            "available":
                False,

            "batting":
                batting,

            "market_used":
                False,
        }

    opportunity = (
        opportunity_context(
            hitter_name,
            pitcher_name,
            season,
            batting_order,
        )
    )

    transition = (
        starter_bullpen_transition(
            hitter_name,
            season,
            batting[
                "per_pa_events"
            ],
            opportunity,
        )
    )

    environment = (
        apply_environment_to_event_tree(
            transition[
                "blended_event_tree"
            ],
            weather=weather,
            park_factor=park_factor,
        )
    )

    baserunning = (
        baserunning_profile(
            hitter_name,
            pitcher_name,
            season,
            {
                "per_pa_events":
                    environment[
                        "event_tree"
                    ]
            },
        )
    )

    final_tree = (
        environment[
            "event_tree"
        ]
    )

    hit_per_pa = (
        final_tree.get(
            "single",
            0.0,
        )
        + final_tree.get(
            "double",
            0.0,
        )
        + final_tree.get(
            "triple",
            0.0,
        )
        + final_tree.get(
            "home_run",
            0.0,
        )
    )

    tb_per_pa = (
        final_tree.get(
            "single",
            0.0,
        )
        + 2.0
        * final_tree.get(
            "double",
            0.0,
        )
        + 3.0
        * final_tree.get(
            "triple",
            0.0,
        )
        + 4.0
        * final_tree.get(
            "home_run",
            0.0,
        )
    )

    expected_pa = (
        opportunity.get(
            "expected_plate_appearances"
        )
    )

    return {
        "available":
            True,

        "hitter":
            batting["hitter"],

        "pitcher":
            batting["pitcher"],

        "opportunity":
            opportunity,

        "starter_bullpen":
            transition,

        "environment":
            environment,

        "baserunning":
            baserunning,

        "final_event_tree":
            final_tree,

        "hit_probability_per_pa":
            hit_per_pa,

        "tb_expectation_per_pa":
            tb_per_pa,

        "expected_hits":
            (
                expected_pa
                * hit_per_pa
                if expected_pa
                is not None
                else None
            ),

        "expected_total_bases":
            (
                expected_pa
                * tb_per_pa
                if expected_pa
                is not None
                else None
            ),

        "expected_stolen_bases":
            (
                expected_pa
                * baserunning[
                    "stolen_base_probability_per_pa"
                ]
                if expected_pa
                is not None
                else None
            ),

        "market_used":
            False,

        "prediction_created":
            False,

        "recommendation_created":
            False,
    }


def print_matchup_context_v2(
    result,
):
    print()
    print("=" * 72)
    print(
        "STEPS 5-8 — COMPLETE MATCHUP CONTEXT AUDIT"
    )
    print("=" * 72)

    if not result.get(
        "available"
    ):
        print(
            "AVAILABLE: False"
        )
        print("=" * 72)
        return

    h = result["hitter"]
    p = result["pitcher"]

    print(
        f"{h['name']} "
        f"({h.get('bat_side') or '?'})"
    )

    print("vs")

    print(
        f"{p['name']} "
        f"({p.get('pitch_hand') or '?'})"
    )

    print()

    opp = result[
        "opportunity"
    ]

    print(
        "OPPORTUNITY:"
    )

    print(
        "  Batting order:",
        opp.get(
            "batting_order"
        ),
    )

    print(
        "  Expected PA:",
        _fmt_num(
            opp.get(
                "expected_plate_appearances"
            ),
            2,
        ),
    )

    workload = opp[
        "pitcher_workload"
    ]

    print(
        "  Starter expected outs:",
        _fmt_num(
            workload.get(
                "expected_outs"
            ),
            2,
        ),
    )

    print(
        "  Starter expected BF:",
        _fmt_num(
            workload.get(
                "expected_batters_faced"
            ),
            2,
        ),
    )

    print(
        "  Starter expected pitches:",
        _fmt_num(
            workload.get(
                "expected_pitches"
            ),
            1,
        ),
    )

    print()

    transition = result[
        "starter_bullpen"
    ]

    print(
        "STARTER / BULLPEN:"
    )

    print(
        "  Starter exposure:",
        _fmt_pct(
            transition[
                "starter_exposure"
            ]
        ),
    )

    print(
        "  Bullpen exposure:",
        _fmt_pct(
            transition[
                "bullpen_exposure"
            ]
        ),
    )

    print(
        "  Source:",
        transition[
            "exposure_source"
        ],
    )

    print(
        "  Bullpen model:",
        transition[
            "bullpen_model"
        ],
    )

    print()

    sb = result[
        "baserunning"
    ]

    print(
        "BASERUNNING:"
    )

    print(
        "  Reach / PA:",
        _fmt_pct(
            sb[
                "reach_probability_per_pa"
            ]
        ),
    )

    print(
        "  Attempt | reach:",
        _fmt_pct(
            sb[
                "attempt_rate_given_reach"
            ]
        ),
    )

    print(
        "  Success | attempt:",
        _fmt_pct(
            sb[
                "success_rate_given_attempt"
            ]
        ),
    )

    print(
        "  SB probability / PA:",
        _fmt_pct(
            sb[
                "stolen_base_probability_per_pa"
            ]
        ),
    )

    print()

    env = result[
        "environment"
    ]

    print(
        "ENVIRONMENT:"
    )

    print(
        "  Weather verified:",
        env[
            "weather"
        ][
            "verified"
        ],
    )

    print(
        "  Weather signals:",
        env[
            "weather"
        ][
            "signals"
        ],
    )

    print(
        "  Park verified:",
        env[
            "park"
        ][
            "verified"
        ],
    )

    print()

    print(
        "FINAL EVENT TREE:"
    )

    for key, value in (
        result[
            "final_event_tree"
        ].items()
    ):
        print(
            f"  {key:<15}",
            _fmt_pct(value),
        )

    print()

    print(
        "Expected hits:",
        _fmt_num(
            result[
                "expected_hits"
            ],
            3,
        ),
    )

    print(
        "Expected total bases:",
        _fmt_num(
            result[
                "expected_total_bases"
            ],
            3,
        ),
    )

    print(
        "Expected stolen bases:",
        _fmt_num(
            result[
                "expected_stolen_bases"
            ],
            3,
        ),
    )

    print(
        "Event total:",
        f"{sum(result['final_event_tree'].values()):.6f}",
    )

    print()

    print(
        "Market used:",
        result[
            "market_used"
        ],
    )

    print(
        "PrizePicks prediction:",
        result[
            "prediction_created"
        ],
    )

    print(
        "Recommendation:",
        result[
            "recommendation_created"
        ],
    )

    print("=" * 72)


