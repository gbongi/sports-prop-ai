import argparse
import csv
import math
import random
from pathlib import Path

from mlb_matchup_engine import matchup_context_v2


MODEL_VERSION = "MLB_V2_SIM_0.1"
DEFAULT_SIMULATIONS = 1000
DEFAULT_SEED = 20260924


def _draw_event(event_tree, rng):
    x = rng.random()
    running = 0.0

    for event, probability in event_tree.items():
        running += float(probability or 0.0)

        if x <= running:
            return event

    return list(event_tree.keys())[-1]


def _sample_plate_appearances(expected_pa, rng):
    """
    Convert fractional expected PA into realistic integer PA.

    Example:
        expected PA = 4.15
        -> usually 4 PA
        -> 15% chance of 5 PA

    This preserves the expected value without pretending
    every game has exactly 4.15 plate appearances.
    """

    expected_pa = max(1.0, float(expected_pa))

    lower = int(math.floor(expected_pa))
    fraction = expected_pa - lower

    return (
        lower + 1
        if rng.random() < fraction
        else lower
    )


def _simulate_stolen_base(
    event,
    baserunning,
    rng,
):
    """
    SB opportunity only occurs after reaching base on
    an eligible event.

    HR does not create an SB opportunity.
    """

    if event not in {
        "walk",
        "hit_by_pitch",
        "single",
        "double",
        "triple",
    }:
        return 0

    attempt_rate = float(
        baserunning.get(
            "attempt_rate_given_reach",
            0.0,
        )
        or 0.0
    )

    success_rate = float(
        baserunning.get(
            "success_rate_given_attempt",
            0.0,
        )
        or 0.0
    )

    if rng.random() >= attempt_rate:
        return 0

    return (
        1
        if rng.random() < success_rate
        else 0
    )


def simulate_hitter_game(
    context,
    rng,
):
    tree = context["final_event_tree"]

    expected_pa = context[
        "opportunity"
    ][
        "expected_plate_appearances"
    ]

    pa = _sample_plate_appearances(
        expected_pa,
        rng,
    )

    result = {
        "plate_appearances": pa,
        "strikeouts": 0,
        "walks": 0,
        "hbp": 0,
        "singles": 0,
        "doubles": 0,
        "triples": 0,
        "home_runs": 0,
        "hits": 0,
        "total_bases": 0,
        "stolen_bases": 0,
    }

    for _ in range(pa):
        event = _draw_event(
            tree,
            rng,
        )

        if event == "strikeout":
            result["strikeouts"] += 1

        elif event == "walk":
            result["walks"] += 1

        elif event == "hit_by_pitch":
            result["hbp"] += 1

        elif event == "single":
            result["singles"] += 1
            result["hits"] += 1
            result["total_bases"] += 1

        elif event == "double":
            result["doubles"] += 1
            result["hits"] += 1
            result["total_bases"] += 2

        elif event == "triple":
            result["triples"] += 1
            result["hits"] += 1
            result["total_bases"] += 3

        elif event == "home_run":
            result["home_runs"] += 1
            result["hits"] += 1
            result["total_bases"] += 4

        result["stolen_bases"] += (
            _simulate_stolen_base(
                event,
                context["baserunning"],
                rng,
            )
        )

    return result


def _average(results, key):
    if not results:
        return 0.0

    return (
        sum(
            float(row[key])
            for row in results
        )
        / len(results)
    )


def _distribution(results, key):
    counts = {}

    for row in results:
        value = int(row[key])

        counts[value] = (
            counts.get(value, 0)
            + 1
        )

    total = len(results)

    return {
        value: count / total
        for value, count
        in sorted(counts.items())
    }


def prop_probability(
    results,
    key,
    line,
):
    """
    PrizePicks-style comparison.

    Integer lines can produce pushes.

    MORE = simulated value > line
    LESS = simulated value < line
    PUSH = simulated value == line
    """

    line = float(line)

    more = 0
    less = 0
    push = 0

    for row in results:
        value = float(row[key])

        if value > line:
            more += 1

        elif value < line:
            less += 1

        else:
            push += 1

    total = len(results)

    return {
        "more":
            more / total,

        "less":
            less / total,

        "push":
            push / total,
    }


def recommendation(probabilities, threshold=0.58):
    """
    Direction and recommendation are intentionally separate.

    PASS does NOT mean the direction cannot cash.
    It means the simulated edge is below our action threshold.
    """

    more = probabilities["more"]
    less = probabilities["less"]

    if more >= less:
        direction = "MORE"
        direction_probability = more

    else:
        direction = "LESS"
        direction_probability = less

    if direction_probability >= threshold:
        pick = direction
    else:
        pick = "PASS"

    return {
        "direction": direction,
        "direction_probability":
            direction_probability,
        "recommendation": pick,
    }


def simulate_matchup(
    hitter_name,
    pitcher_name,
    season,
    batting_order=None,
    simulations=DEFAULT_SIMULATIONS,
    seed=DEFAULT_SEED,
    start_date=None,
    end_date=None,
):
    context = matchup_context_v2(
        hitter_name,
        pitcher_name,
        season,
        batting_order=batting_order,
        start_date=start_date,
        end_date=end_date,
    )

    if not context.get("available"):
        raise RuntimeError(
            "V2 matchup context unavailable."
        )

    rng = random.Random(seed)

    results = [
        simulate_hitter_game(
            context,
            rng,
        )
        for _ in range(simulations)
    ]

    return {
        "model_version": MODEL_VERSION,
        "hitter": hitter_name,
        "pitcher": pitcher_name,
        "season": season,
        "simulations": simulations,
        "seed": seed,
        "context": context,
        "results": results,
    }


def save_summary_csv(sim):
    path = Path(
        "database/mlb_v2_predictions.csv"
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    exists = path.exists()

    context = sim["context"]
    results = sim["results"]

    row = {
        "model_version":
            sim["model_version"],

        "hitter":
            sim["hitter"],

        "pitcher":
            sim["pitcher"],

        "season":
            sim["season"],

        "simulations":
            sim["simulations"],

        "seed":
            sim["seed"],

        "expected_pa":
            context["opportunity"][
                "expected_plate_appearances"
            ],

        "simulated_pa":
            _average(
                results,
                "plate_appearances",
            ),

        "analytical_hits":
            context[
                "expected_hits"
            ],

        "simulated_hits":
            _average(
                results,
                "hits",
            ),

        "analytical_total_bases":
            context[
                "expected_total_bases"
            ],

        "simulated_total_bases":
            _average(
                results,
                "total_bases",
            ),

        "analytical_stolen_bases":
            context[
                "expected_stolen_bases"
            ],

        "simulated_stolen_bases":
            _average(
                results,
                "stolen_bases",
            ),

        "market_used":
            False,
    }

    with path.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(row.keys()),
        )

        if not exists:
            writer.writeheader()

        writer.writerow(row)

    return path


def print_distribution(label, distribution):
    parts = []

    for value, probability in (
        distribution.items()
    ):
        if value >= 4:
            continue

        parts.append(
            f"{value}={probability:.1%}"
        )

    tail = sum(
        probability
        for value, probability
        in distribution.items()
        if value >= 4
    )

    if tail > 0:
        parts.append(
            f"4+={tail:.1%}"
        )

    print(
        f"{label}: "
        + " | ".join(parts)
    )


def print_audit(sim):
    context = sim["context"]
    results = sim["results"]

    analytical_pa = context[
        "opportunity"
    ][
        "expected_plate_appearances"
    ]

    analytical_hits = context[
        "expected_hits"
    ]

    analytical_tb = context[
        "expected_total_bases"
    ]

    analytical_sb = context[
        "expected_stolen_bases"
    ]

    simulated_pa = _average(
        results,
        "plate_appearances",
    )

    simulated_hits = _average(
        results,
        "hits",
    )

    simulated_tb = _average(
        results,
        "total_bases",
    )

    simulated_sb = _average(
        results,
        "stolen_bases",
    )

    print()
    print("=" * 72)
    print(
        "MLB V2 — 1,000 RUN HITTER SIMULATION"
    )
    print("=" * 72)

    print(
        f"{sim['hitter']} vs "
        f"{sim['pitcher']}"
    )

    print(
        "Model:",
        sim["model_version"],
    )

    print(
        "Simulations:",
        sim["simulations"],
    )

    print(
        "Seed:",
        sim["seed"],
    )

    print()

    print(
        "ANALYTICAL vs SIMULATED"
    )

    print(
        f"PA:   {analytical_pa:.3f}"
        f" -> {simulated_pa:.3f}"
    )

    print(
        f"Hits: {analytical_hits:.3f}"
        f" -> {simulated_hits:.3f}"
    )

    print(
        f"TB:   {analytical_tb:.3f}"
        f" -> {simulated_tb:.3f}"
    )

    print(
        f"SB:   {analytical_sb:.3f}"
        f" -> {simulated_sb:.3f}"
    )

    print()

    print_distribution(
        "HITS",
        _distribution(
            results,
            "hits",
        ),
    )

    print_distribution(
        "TOTAL BASES",
        _distribution(
            results,
            "total_bases",
        ),
    )

    print_distribution(
        "HOME RUNS",
        _distribution(
            results,
            "home_runs",
        ),
    )

    print()

    for prop, key, line in [
        ("Hits", "hits", 0.5),
        (
            "Total Bases",
            "total_bases",
            1.5,
        ),
        (
            "Home Runs",
            "home_runs",
            0.5,
        ),
    ]:
        probabilities = (
            prop_probability(
                results,
                key,
                line,
            )
        )

        decision = recommendation(
            probabilities
        )

        print(
            f"{prop} {line}"
        )

        print(
            "  P(MORE):",
            f"{probabilities['more']:.1%}",
        )

        print(
            "  P(LESS):",
            f"{probabilities['less']:.1%}",
        )

        print(
            "  PUSH:",
            f"{probabilities['push']:.1%}",
        )

        print(
            "  MODEL DIRECTION:",
            decision["direction"],
        )

        print(
            "  RECOMMENDATION:",
            decision[
                "recommendation"
            ],
        )

        print()

    print(
        "Market used: False"
    )

    print(
        "Runs/RBI/HFS: "
        "NOT YET ENABLED"
    )

    print(
        "Pitcher props/PFS: "
        "NOT YET ENABLED"
    )

    print("=" * 72)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "hitter"
    )

    parser.add_argument(
        "pitcher"
    )

    parser.add_argument(
        "--season",
        type=int,
        default=2026,
    )

    parser.add_argument(
        "--batting-order",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--simulations",
        type=int,
        default=DEFAULT_SIMULATIONS,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
    )

    parser.add_argument(
        "--start-date",
        default=None,
    )

    parser.add_argument(
        "--end-date",
        default=None,
    )

    args = parser.parse_args()

    sim = simulate_matchup(
        args.hitter,
        args.pitcher,
        args.season,
        batting_order=args.batting_order,
        simulations=args.simulations,
        seed=args.seed,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    print_audit(sim)

    path = save_summary_csv(sim)

    print()
    print(
        "CSV:",
        path,
    )


if __name__ == "__main__":
    main()


# ============================================================
# MLB V2 FULL SIMULATION EXTENSION
#
# HITTER:
#   Runs / RBI / exact PrizePicks HFS
#
# PITCHER:
#   K / Outs / Hits Allowed / Walks Allowed / ER / PFS
#
# IMPORTANT:
#   - Baseball data only.
#   - No PrizePicks line used to create projection.
#   - No market used.
#   - Missing context remains pending.
# ============================================================


# ============================================================
# HITTER RUN / RBI CONTEXT
# ============================================================

def _historical_hitter_run_rbi_rates(
    player_name,
    season,
):
    """
    Historical per-PA Run and RBI rates.

    These are BASELINES, not fixed fantasy-score bonuses.
    """

    from mlb_matchup_engine import (
        find_player,
        player_game_log,
        _statcast_float,
    )

    player = find_player(player_name)

    if not player:
        return {
            "run_per_pa": None,
            "rbi_per_pa": None,
            "sample_pa": 0.0,
        }

    games = player_game_log(
        int(player["id"]),
        int(season),
        "hitting",
    )

    total_pa = 0.0
    total_runs = 0.0
    total_rbi = 0.0

    for game in games:
        stat = game.get("stat") or {}

        pa = _statcast_float(
            stat.get("plateAppearances")
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

        total_pa += pa or 0.0

        total_runs += (
            _statcast_float(
                stat.get("runs")
            )
            or 0.0
        )

        total_rbi += (
            _statcast_float(
                stat.get("rbi")
            )
            or 0.0
        )

    if total_pa <= 0:
        return {
            "run_per_pa": None,
            "rbi_per_pa": None,
            "sample_pa": 0.0,
        }

    return {
        "run_per_pa":
            total_runs / total_pa,

        "rbi_per_pa":
            total_rbi / total_pa,

        "sample_pa":
            total_pa,
    }


def _lineup_run_rbi_adjustment(
    batting_order,
):
    """
    Small role adjustment only.

    This is intentionally conservative.

    Top/middle lineup positions affect run/RBI opportunity,
    but batting order never determines whether a player
    can cash a prop.
    """

    run_mult = {
        1: 1.08,
        2: 1.06,
        3: 1.04,
        4: 1.00,
        5: 0.98,
        6: 0.96,
        7: 0.94,
        8: 0.92,
        9: 0.90,
    }.get(
        batting_order,
        1.0,
    )

    rbi_mult = {
        1: 0.92,
        2: 0.96,
        3: 1.04,
        4: 1.10,
        5: 1.06,
        6: 1.00,
        7: 0.96,
        8: 0.93,
        9: 0.90,
    }.get(
        batting_order,
        1.0,
    )

    return {
        "run_multiplier":
            run_mult,

        "rbi_multiplier":
            rbi_mult,
    }


def hitter_run_rbi_context(
    player_name,
    season,
    batting_order=None,
):
    baseline = (
        _historical_hitter_run_rbi_rates(
            player_name,
            season,
        )
    )

    lineup = (
        _lineup_run_rbi_adjustment(
            batting_order
        )
    )

    run_rate = baseline.get(
        "run_per_pa"
    )

    rbi_rate = baseline.get(
        "rbi_per_pa"
    )

    if run_rate is not None:
        run_rate = max(
            0.0,
            min(
                0.60,
                run_rate
                * lineup[
                    "run_multiplier"
                ],
            ),
        )

    if rbi_rate is not None:
        rbi_rate = max(
            0.0,
            min(
                0.70,
                rbi_rate
                * lineup[
                    "rbi_multiplier"
                ],
            ),
        )

    return {
        "run_probability_per_pa":
            run_rate,

        "rbi_expectation_per_pa":
            rbi_rate,

        "sample_pa":
            baseline[
                "sample_pa"
            ],

        "batting_order":
            batting_order,

        "lineup_adjustment":
            lineup,

        "full_team_state_model":
            False,

        "readiness":
            (
                "BASELINE_READY"
                if (
                    run_rate is not None
                    and rbi_rate is not None
                )
                else "PENDING"
            ),

        "market_used":
            False,
    }


def _poisson_sample(lam, rng):
    """
    Knuth Poisson sampler.
    Fine for the small RBI/ER rates used here.
    """

    if lam <= 0:
        return 0

    limit = math.exp(-lam)

    k = 0
    product = 1.0

    while product > limit:
        k += 1
        product *= rng.random()

    return k - 1


def _simulate_hitter_run_rbi(
    game,
    run_rbi,
    rng,
):
    """
    Add Runs/RBI without pretending we have a complete
    base-state simulator yet.

    HR guarantees at least one Run and one RBI.

    Remaining run/RBI opportunities use the player's
    historical role baseline.

    Later full lineup/base-state simulation can replace
    this module without changing HFS scoring.
    """

    pa = game[
        "plate_appearances"
    ]

    hr = game[
        "home_runs"
    ]

    run_rate = (
        run_rbi.get(
            "run_probability_per_pa"
        )
    )

    rbi_rate = (
        run_rbi.get(
            "rbi_expectation_per_pa"
        )
    )

    if run_rate is None:
        runs = hr
    else:
        non_hr_pa = max(
            0,
            pa - hr,
        )

        extra_runs = sum(
            1
            for _ in range(
                non_hr_pa
            )
            if rng.random()
            < min(
                0.45,
                run_rate,
            )
        )

        runs = (
            hr + extra_runs
        )

    if rbi_rate is None:
        rbi = hr
    else:
        # HR guarantees the batter himself scores and
        # therefore guarantees at least one RBI.
        remaining_expectation = max(
            0.0,
            pa * rbi_rate - hr,
        )

        rbi = (
            hr
            + _poisson_sample(
                remaining_expectation,
                rng,
            )
        )

    game["runs"] = runs
    game["rbi"] = rbi

    return game


def _hitter_fantasy_score(game):
    """
    Exact PrizePicks MLB Hitter Fantasy Score.

    1B = 3
    2B = 5
    3B = 8
    HR = 10
    BB = 2
    HBP = 2
    SB = 5
    Run = 2
    RBI = 2
    """

    return (
        3 * game["singles"]
        + 5 * game["doubles"]
        + 8 * game["triples"]
        + 10 * game["home_runs"]
        + 2 * game["walks"]
        + 2 * game["hbp"]
        + 5 * game["stolen_bases"]
        + 2 * game["runs"]
        + 2 * game["rbi"]
    )


def simulate_hitter_game_full(
    context,
    run_rbi,
    rng,
):
    game = simulate_hitter_game(
        context,
        rng,
    )

    game = _simulate_hitter_run_rbi(
        game,
        run_rbi,
        rng,
    )

    game[
        "hitter_fantasy_score"
    ] = _hitter_fantasy_score(
        game
    )

    return game


# ============================================================
# PITCHER HISTORICAL PROFILE
# ============================================================

def _pitcher_simulation_baseline(
    pitcher_name,
    season,
):
    from mlb_matchup_engine import (
        find_player,
        player_game_log,
        _statcast_float,
    )

    player = find_player(
        pitcher_name
    )

    if not player:
        return {
            "available": False,
        }

    games = player_game_log(
        int(player["id"]),
        int(season),
        "pitching",
    )

    rows = []

    for game in games[-20:]:
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
            whole, frac = (
                ip.split(".")
            )

            outs = (
                int(whole) * 3
                + int(frac)
            )

        except Exception:
            outs = int(
                (
                    _statcast_float(ip)
                    or 0.0
                )
                * 3
            )

        rows.append({
            "outs":
                float(outs),

            "strikeouts":
                _statcast_float(
                    stat.get(
                        "strikeOuts"
                    )
                )
                or 0.0,

            "hits_allowed":
                _statcast_float(
                    stat.get(
                        "hits"
                    )
                )
                or 0.0,

            "walks_allowed":
                _statcast_float(
                    stat.get(
                        "baseOnBalls"
                    )
                )
                or 0.0,

            "earned_runs":
                _statcast_float(
                    stat.get(
                        "earnedRuns"
                    )
                )
                or 0.0,

            "batters_faced":
                _statcast_float(
                    stat.get(
                        "battersFaced"
                    )
                )
                or 0.0,

            "pitches":
                (
                    _statcast_float(
                        stat.get(
                            "numberOfPitches"
                        )
                    )
                    or _statcast_float(
                        stat.get(
                            "pitchesThrown"
                        )
                    )
                    or 0.0
                ),

            "win":
                1
                if (
                    _statcast_float(
                        stat.get("wins")
                    )
                    or 0.0
                ) > 0
                else 0,
        })

    if not rows:
        return {
            "available": False,
        }

    def avg(key):
        values = [
            row[key]
            for row in rows
        ]

        return (
            sum(values)
            / len(values)
        )

    total_bf = sum(
        row["batters_faced"]
        for row in rows
    )

    if total_bf > 0:
        k_per_bf = (
            sum(
                row["strikeouts"]
                for row in rows
            )
            / total_bf
        )

        hit_per_bf = (
            sum(
                row["hits_allowed"]
                for row in rows
            )
            / total_bf
        )

        walk_per_bf = (
            sum(
                row["walks_allowed"]
                for row in rows
            )
            / total_bf
        )

        er_per_bf = (
            sum(
                row["earned_runs"]
                for row in rows
            )
            / total_bf
        )

    else:
        k_per_bf = 0.0
        hit_per_bf = 0.0
        walk_per_bf = 0.0
        er_per_bf = 0.0

    return {
        "available":
            True,

        "sample_games":
            len(rows),

        "expected_outs":
            avg("outs"),

        "expected_bf":
            avg(
                "batters_faced"
            ),

        "expected_pitches":
            avg("pitches"),

        "k_per_bf":
            k_per_bf,

        "hit_per_bf":
            hit_per_bf,

        "walk_per_bf":
            walk_per_bf,

        "er_per_bf":
            er_per_bf,

        "historical_win_rate":
            avg("win"),

        "rows":
            rows,
    }


def _sample_pitcher_workload(
    baseline,
    rng,
):
    """
    Bootstrap workload from real recent starts rather than
    assuming every start has identical innings/BF.
    """

    row = rng.choice(
        baseline["rows"]
    )

    outs = int(
        round(
            row["outs"]
        )
    )

    bf = int(
        round(
            row["batters_faced"]
        )
    )

    if bf <= 0:
        bf = max(
            1,
            int(
                round(
                    baseline[
                        "expected_bf"
                    ]
                )
            ),
        )

    return {
        "outs":
            max(
                0,
                outs,
            ),

        "batters_faced":
            max(
                1,
                bf,
            ),
    }


def _blend_pitcher_k_rate_with_matchup(
    baseline_k_rate,
    hitter_context=None,
):
    """
    Foundation for confirmed-lineup pitcher simulation.

    If a hitter matchup is supplied, blend the pitcher's
    historical K/BF with that hitter's V2 K probability.

    Without a verified lineup matchup, historical pitcher
    rate remains the anchor.
    """

    if not hitter_context:
        return baseline_k_rate

    tree = hitter_context.get(
        "final_event_tree",
        {}
    )

    hitter_k = tree.get(
        "strikeout"
    )

    if hitter_k is None:
        return baseline_k_rate

    return (
        0.55
        * baseline_k_rate
        + 0.45
        * hitter_k
    )


def simulate_pitcher_game(
    baseline,
    rng,
    lineup_contexts=None,
    win_probability=None,
):
    workload = (
        _sample_pitcher_workload(
            baseline,
            rng,
        )
    )

    bf = workload[
        "batters_faced"
    ]

    outs = workload["outs"]

    strikeouts = 0
    hits_allowed = 0
    walks_allowed = 0

    lineup_contexts = (
        lineup_contexts
        or []
    )

    for index in range(bf):
        hitter_context = (
            lineup_contexts[
                index
                % len(
                    lineup_contexts
                )
            ]
            if lineup_contexts
            else None
        )

        k_rate = (
            _blend_pitcher_k_rate_with_matchup(
                baseline[
                    "k_per_bf"
                ],
                hitter_context,
            )
        )

        if hitter_context:
            tree = (
                hitter_context.get(
                    "final_event_tree",
                    {}
                )
            )

            hit_rate = (
                tree.get(
                    "single",
                    0.0,
                )
                + tree.get(
                    "double",
                    0.0,
                )
                + tree.get(
                    "triple",
                    0.0,
                )
                + tree.get(
                    "home_run",
                    0.0,
                )
            )

            walk_rate = (
                tree.get(
                    "walk",
                    baseline[
                        "walk_per_bf"
                    ],
                )
            )

            # Shrink individual matchup rates toward the
            # pitcher's established history.
            hit_rate = (
                0.55
                * baseline[
                    "hit_per_bf"
                ]
                + 0.45
                * hit_rate
            )

            walk_rate = (
                0.55
                * baseline[
                    "walk_per_bf"
                ]
                + 0.45
                * walk_rate
            )

        else:
            hit_rate = baseline[
                "hit_per_bf"
            ]

            walk_rate = baseline[
                "walk_per_bf"
            ]

        x = rng.random()

        # Mutually exclusive simplified BF outcome tree.
        if x < k_rate:
            strikeouts += 1

        elif x < (
            k_rate
            + walk_rate
        ):
            walks_allowed += 1

        elif x < (
            k_rate
            + walk_rate
            + hit_rate
        ):
            hits_allowed += 1

    # ER is currently anchored to historical ER/BF and
    # modified slightly by simulated traffic.
    expected_er = (
        baseline[
            "er_per_bf"
        ]
        * bf
    )

    historical_traffic = (
        baseline[
            "hit_per_bf"
        ]
        + baseline[
            "walk_per_bf"
        ]
    )

    simulated_traffic = (
        (
            hits_allowed
            + walks_allowed
        )
        / bf
    )

    if historical_traffic > 0:
        traffic_ratio = (
            simulated_traffic
            / historical_traffic
        )

        traffic_ratio = max(
            0.65,
            min(
                1.40,
                traffic_ratio,
            ),
        )

        expected_er *= (
            0.70
            + 0.30
            * traffic_ratio
        )

    earned_runs = (
        _poisson_sample(
            max(
                0.0,
                expected_er,
            ),
            rng,
        )
    )

    # Win is intentionally NOT assumed.
    # If no defensible win probability is supplied,
    # no win points are awarded and PFS is marked pending.
    if win_probability is None:
        win = 0
        win_verified = False

    else:
        win = (
            1
            if rng.random()
            < win_probability
            else 0
        )

        win_verified = True

    quality_start = (
        1
        if (
            outs >= 18
            and earned_runs <= 3
        )
        else 0
    )

    pfs_without_win = (
        outs
        + 3 * strikeouts
        - 3 * earned_runs
        + 4 * quality_start
    )

    pfs = (
        pfs_without_win
        + 6 * win
    )

    return {
        "pitching_outs":
            outs,

        "strikeouts":
            strikeouts,

        "hits_allowed":
            hits_allowed,

        "walks_allowed":
            walks_allowed,

        "earned_runs":
            earned_runs,

        "quality_start":
            quality_start,

        "win":
            win,

        "win_verified":
            win_verified,

        "pitcher_fantasy_score":
            pfs,

        "pitcher_fantasy_score_without_win":
            pfs_without_win,
    }


# ============================================================
# FULL HITTER SIMULATION
# ============================================================

def simulate_hitter_matchup_full(
    hitter_name,
    pitcher_name,
    season,
    batting_order=None,
    simulations=1000,
    seed=20260924,
    start_date=None,
    end_date=None,
):
    context = matchup_context_v2(
        hitter_name,
        pitcher_name,
        season,
        batting_order=batting_order,
        start_date=start_date,
        end_date=end_date,
    )

    if not context.get(
        "available"
    ):
        raise RuntimeError(
            "V2 hitter context unavailable."
        )

    run_rbi = (
        hitter_run_rbi_context(
            hitter_name,
            season,
            batting_order,
        )
    )

    rng = random.Random(
        seed
    )

    results = [
        simulate_hitter_game_full(
            context,
            run_rbi,
            rng,
        )
        for _ in range(
            simulations
        )
    ]

    return {
        "model_version":
            "MLB_V2_SIM_0.2",

        "hitter":
            hitter_name,

        "pitcher":
            pitcher_name,

        "season":
            season,

        "simulations":
            simulations,

        "seed":
            seed,

        "context":
            context,

        "run_rbi_context":
            run_rbi,

        "results":
            results,

        "market_used":
            False,
    }


def simulate_pitcher_matchup_full(
    pitcher_name,
    season,
    simulations=1000,
    seed=20260924,
    lineup_contexts=None,
    win_probability=None,
):
    baseline = (
        _pitcher_simulation_baseline(
            pitcher_name,
            season,
        )
    )

    if not baseline.get(
        "available"
    ):
        raise RuntimeError(
            "Pitcher baseline unavailable."
        )

    rng = random.Random(
        seed
    )

    results = [
        simulate_pitcher_game(
            baseline,
            rng,
            lineup_contexts=
                lineup_contexts,
            win_probability=
                win_probability,
        )
        for _ in range(
            simulations
        )
    ]

    return {
        "model_version":
            "MLB_V2_SIM_0.2",

        "pitcher":
            pitcher_name,

        "season":
            season,

        "simulations":
            simulations,

        "seed":
            seed,

        "baseline":
            baseline,

        "lineup_verified":
            bool(
                lineup_contexts
            ),

        "win_model_verified":
            (
                win_probability
                is not None
            ),

        "results":
            results,

        "market_used":
            False,
    }


# ============================================================
# PROP RESULT ENGINE
# ============================================================

def simulated_prop_result(
    results,
    stat_key,
    line,
    threshold=0.58,
):
    probabilities = (
        prop_probability(
            results,
            stat_key,
            line,
        )
    )

    decision = recommendation(
        probabilities,
        threshold=threshold,
    )

    projection = _average(
        results,
        stat_key,
    )

    return {
        "prop":
            stat_key,

        "line":
            float(line),

        "projection":
            projection,

        "p_more":
            probabilities[
                "more"
            ],

        "p_less":
            probabilities[
                "less"
            ],

        "p_push":
            probabilities[
                "push"
            ],

        "model_direction":
            decision[
                "direction"
            ],

        "direction_probability":
            decision[
                "direction_probability"
            ],

        "recommendation":
            decision[
                "recommendation"
            ],
    }


def print_full_hitter_audit(
    sim,
):
    results = sim[
        "results"
    ]

    print()
    print("=" * 72)
    print(
        "MLB V2 — FULL HITTER SIMULATION"
    )
    print("=" * 72)

    print(
        sim["hitter"],
        "vs",
        sim["pitcher"],
    )

    print(
        "Simulations:",
        sim[
            "simulations"
        ],
    )

    print()

    for label, key in [
        ("PA", "plate_appearances"),
        ("Hits", "hits"),
        ("TB", "total_bases"),
        ("HR", "home_runs"),
        ("BB", "walks"),
        ("SB", "stolen_bases"),
        ("Runs", "runs"),
        ("RBI", "rbi"),
        (
            "Hitter Fantasy Score",
            "hitter_fantasy_score",
        ),
    ]:
        print(
            f"{label:<22}",
            f"{_average(results, key):.3f}",
        )

    print()

    print(
        "Run/RBI context:",
        sim[
            "run_rbi_context"
        ][
            "readiness"
        ],
    )

    print(
        "Full team-state model:",
        sim[
            "run_rbi_context"
        ][
            "full_team_state_model"
        ],
    )

    print(
        "Market used:",
        sim[
            "market_used"
        ],
    )

    print("=" * 72)


def print_full_pitcher_audit(
    sim,
):
    results = sim[
        "results"
    ]

    print()
    print("=" * 72)
    print(
        "MLB V2 — FULL PITCHER SIMULATION"
    )
    print("=" * 72)

    print(
        sim["pitcher"]
    )

    print(
        "Simulations:",
        sim[
            "simulations"
        ],
    )

    print(
        "Lineup verified:",
        sim[
            "lineup_verified"
        ],
    )

    print(
        "Win model verified:",
        sim[
            "win_model_verified"
        ],
    )

    print()

    for label, key in [
        (
            "Strikeouts",
            "strikeouts",
        ),
        (
            "Pitching Outs",
            "pitching_outs",
        ),
        (
            "Hits Allowed",
            "hits_allowed",
        ),
        (
            "Walks Allowed",
            "walks_allowed",
        ),
        (
            "Earned Runs",
            "earned_runs",
        ),
        (
            "Quality Start %",
            "quality_start",
        ),
        (
            "PFS no Win",
            "pitcher_fantasy_score_without_win",
        ),
        (
            "Pitcher Fantasy Score",
            "pitcher_fantasy_score",
        ),
    ]:
        value = _average(
            results,
            key,
        )

        if key == (
            "quality_start"
        ):
            print(
                f"{label:<22}",
                f"{value:.1%}",
            )

        else:
            print(
                f"{label:<22}",
                f"{value:.3f}",
            )

    print()

    if not sim[
        "lineup_verified"
    ]:
        print(
            "READINESS: PREGAME PENDING "
            "(confirmed opposing lineup not supplied)"
        )

    if not sim[
        "win_model_verified"
    ]:
        print(
            "PFS STATUS: PENDING WIN COMPONENT "
            "(no win probability invented)"
        )

    print(
        "Market used:",
        sim[
            "market_used"
        ],
    )

    print("=" * 72)




# ============================================================
# MLB V2 TEAM-STATE HITTER SIMULATION
# ============================================================

def _team_state_draw_event(
    context,
    rng,
):
    """
    Draw one PA from the hitter's final V2 event tree.

    The final tree already includes:
      hitter profile
      pitcher interaction
      arsenal
      starter/bullpen transition
      environment
    """

    tree = (
        context.get(
            "final_event_tree"
        )
        or {}
    )

    return _draw_event(
        tree,
        rng,
    )


def _empty_hitter_box():
    return {
        "plate_appearances": 0,
        "strikeouts": 0,
        "walks": 0,
        "hbp": 0,
        "singles": 0,
        "doubles": 0,
        "triples": 0,
        "home_runs": 0,
        "hits": 0,
        "total_bases": 0,
        "stolen_bases": 0,
        "runs": 0,
        "rbi": 0,
        "hitter_fantasy_score": 0,
    }


def _score_runner(
    runner,
    boxes,
):
    if runner is None:
        return 0

    boxes[
        runner
    ]["runs"] += 1

    return 1


def _advance_walk(
    batter,
    bases,
    boxes,
):
    """
    Forced advancement for BB/HBP.
    """

    first = bases[0]
    second = bases[1]
    third = bases[2]

    runs = 0

    if first is not None:

        if second is not None:

            if third is not None:
                runs += _score_runner(
                    third,
                    boxes,
                )

            bases[2] = second

        bases[1] = first

    bases[0] = batter

    return runs


def _advance_single(
    batter,
    bases,
    boxes,
    rng,
):
    """
    Conservative stochastic advancement.

    Runner on 3B scores.
    Runner on 2B scores most of the time.
    Runner on 1B occasionally reaches 3B.
    """

    first, second, third = bases

    runs = 0

    if third is not None:
        runs += _score_runner(
            third,
            boxes,
        )

    new_third = None
    new_second = None

    if second is not None:

        if rng.random() < 0.62:
            runs += _score_runner(
                second,
                boxes,
            )
        else:
            new_third = second

    if first is not None:

        if (
            new_third is None
            and rng.random() < 0.28
        ):
            new_third = first
        else:
            new_second = first

    bases[0] = batter
    bases[1] = new_second
    bases[2] = new_third

    return runs


def _advance_double(
    batter,
    bases,
    boxes,
    rng,
):
    first, second, third = bases

    runs = 0

    if third is not None:
        runs += _score_runner(
            third,
            boxes,
        )

    if second is not None:
        runs += _score_runner(
            second,
            boxes,
        )

    new_third = None

    if first is not None:

        if rng.random() < 0.48:
            runs += _score_runner(
                first,
                boxes,
            )
        else:
            new_third = first

    bases[0] = None
    bases[1] = batter
    bases[2] = new_third

    return runs


def _advance_triple(
    batter,
    bases,
    boxes,
):
    runs = 0

    for runner in bases:
        runs += _score_runner(
            runner,
            boxes,
        )

    bases[0] = None
    bases[1] = None
    bases[2] = batter

    return runs


def _advance_home_run(
    batter,
    bases,
    boxes,
):
    runs = 0

    for runner in bases:
        runs += _score_runner(
            runner,
            boxes,
        )

    runs += _score_runner(
        batter,
        boxes,
    )

    bases[0] = None
    bases[1] = None
    bases[2] = None

    return runs


def _maybe_sacrifice_run(
    batter,
    bases,
    outs,
    boxes,
    rng,
):
    """
    Small sac-fly style component.

    We only allow this with:
      runner on 3B
      fewer than 2 outs

    It remains deliberately conservative because the
    current V2 event tree does not separately classify
    sacrifice flies.
    """

    if (
        outs < 2
        and bases[2] is not None
        and rng.random() < 0.18
    ):
        runner = bases[2]

        bases[2] = None

        _score_runner(
            runner,
            boxes,
        )

        boxes[
            batter
        ]["rbi"] += 1

        return 1

    return 0


def _maybe_stolen_base_team_state(
    hitter_index,
    context,
    bases,
    boxes,
    rng,
):
    """
    Use the existing V2 baserunning probabilities.

    Only attempt when the hitter is actually standing
    on first and second base is open.
    """

    if bases[0] != hitter_index:
        return

    if bases[1] is not None:
        return

    baserunning = (
        context.get(
            "baserunning"
        )
        or {}
    )

    attempt = (
        baserunning.get(
            "attempt_probability_given_reach"
        )
    )

    success = (
        baserunning.get(
            "success_probability"
        )
    )

    if attempt is None or success is None:
        return

    attempt = max(
        0.0,
        min(
            1.0,
            float(attempt),
        ),
    )

    success = max(
        0.0,
        min(
            1.0,
            float(success),
        ),
    )

    if rng.random() >= attempt:
        return

    if rng.random() < success:

        bases[1] = hitter_index
        bases[0] = None

        boxes[
            hitter_index
        ]["stolen_bases"] += 1


def simulate_team_offense_game_v2(
    lineup_contexts,
    rng,
    target_index=None,
    innings=9,
):
    """
    Simulate one team's offensive game using its actual
    confirmed batting order.

    This is the first V2 team-state layer.

    It tracks:
      batting order
      outs
      bases
      runs
      RBI
      hitter counting stats
      HFS

    It intentionally does NOT model:
      extra innings
      pinch hitters
      defensive errors
      double plays as a separate calibrated event
      exact home-team bottom-9 cancellation

    Those remain calibration/future refinements.
    """

    if len(
        lineup_contexts
    ) < 9:
        raise ValueError(
            "Team-state simulation requires "
            "9 confirmed hitter contexts."
        )

    boxes = {
        i: _empty_hitter_box()
        for i in range(
            len(lineup_contexts)
        )
    }

    batting_index = 0
    team_runs = 0

    for _inning in range(
        int(innings)
    ):

        outs = 0

        bases = [
            None,
            None,
            None,
        ]

        while outs < 3:

            hitter_index = (
                batting_index
                % len(
                    lineup_contexts
                )
            )

            batting_index += 1

            context = lineup_contexts[
                hitter_index
            ]

            box = boxes[
                hitter_index
            ]

            box[
                "plate_appearances"
            ] += 1

            event = _team_state_draw_event(
                context,
                rng,
            )

            if event == "strikeout":

                box[
                    "strikeouts"
                ] += 1

                outs += 1

            elif event == "walk":

                box[
                    "walks"
                ] += 1

                scored = _advance_walk(
                    hitter_index,
                    bases,
                    boxes,
                )

                box[
                    "rbi"
                ] += scored

                team_runs += scored

                _maybe_stolen_base_team_state(
                    hitter_index,
                    context,
                    bases,
                    boxes,
                    rng,
                )

            elif event == "hbp":

                box[
                    "hbp"
                ] += 1

                scored = _advance_walk(
                    hitter_index,
                    bases,
                    boxes,
                )

                box[
                    "rbi"
                ] += scored

                team_runs += scored

                _maybe_stolen_base_team_state(
                    hitter_index,
                    context,
                    bases,
                    boxes,
                    rng,
                )

            elif event == "single":

                box[
                    "singles"
                ] += 1

                box["hits"] += 1
                box["total_bases"] += 1

                scored = _advance_single(
                    hitter_index,
                    bases,
                    boxes,
                    rng,
                )

                box[
                    "rbi"
                ] += scored

                team_runs += scored

                _maybe_stolen_base_team_state(
                    hitter_index,
                    context,
                    bases,
                    boxes,
                    rng,
                )

            elif event == "double":

                box[
                    "doubles"
                ] += 1

                box["hits"] += 1
                box["total_bases"] += 2

                scored = _advance_double(
                    hitter_index,
                    bases,
                    boxes,
                    rng,
                )

                box[
                    "rbi"
                ] += scored

                team_runs += scored

            elif event == "triple":

                box[
                    "triples"
                ] += 1

                box["hits"] += 1
                box["total_bases"] += 3

                scored = _advance_triple(
                    hitter_index,
                    bases,
                    boxes,
                )

                box[
                    "rbi"
                ] += scored

                team_runs += scored

            elif event == "home_run":

                box[
                    "home_runs"
                ] += 1

                box["hits"] += 1
                box["total_bases"] += 4

                scored = _advance_home_run(
                    hitter_index,
                    bases,
                    boxes,
                )

                box[
                    "rbi"
                ] += scored

                team_runs += scored

            else:
                _maybe_sacrifice_run(
                    hitter_index,
                    bases,
                    outs,
                    boxes,
                    rng,
                )

                outs += 1

    for box in boxes.values():

        box[
            "hitter_fantasy_score"
        ] = _hitter_fantasy_score(
            box
        )

    result = {
        "team_runs":
            team_runs,

        "boxes":
            boxes,

        "batters":
            batting_index,

        "full_team_state_model":
            True,

        "market_used":
            False,
    }

    if target_index is not None:
        result[
            "target"
        ] = boxes[
            int(target_index)
        ]

    return result


def simulate_confirmed_lineup_hitter_v2(
    lineup_contexts,
    target_index,
    simulations=1000,
    seed=20260924,
):
    """
    Monte Carlo wrapper around the team-state game.
    """

    import random

    rng = random.Random(
        seed
    )

    results = []

    team_runs = []

    for _ in range(
        int(simulations)
    ):

        game = simulate_team_offense_game_v2(
            lineup_contexts,
            rng,
            target_index=target_index,
        )

        results.append(
            game["target"]
        )

        team_runs.append(
            game["team_runs"]
        )

    return {
        "model_version":
            "MLB_V2_TEAMSTATE_0.3",

        "simulations":
            int(simulations),

        "results":
            results,

        "average_team_runs":
            (
                sum(team_runs)
                / len(team_runs)
                if team_runs
                else 0.0
            ),

        "full_team_state_model":
            True,

        "market_used":
            False,
    }
