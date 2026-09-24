#!/usr/bin/env python3

"""
MLB V2 historical projection/distribution calibration.

IMPORTANT:
Historical PrizePicks pregame lines are not available here.

Therefore this script does NOT claim historical PrizePicks
betting win rate.

It evaluates whether MLB V2's simulated distributions are
centered and dispersed reasonably relative to actual MLB
results.

Market data is never used.
"""

import argparse
import math
import statistics
from collections import defaultdict

from mlb_matchup_engine import (
    find_player,
    player_game_log,
)

from mlb_simulator_v2 import (
    _pitcher_simulation_baseline,
)


HITTER_PROPS = (
    "hits",
    "total_bases",
    "home_runs",
    "walks",
)

PITCHER_PROPS = (
    "strikeouts",
    "pitching_outs",
    "hits_allowed",
    "walks_allowed",
    "earned_runs",
)


def _float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _innings_to_outs(value):
    text = str(
        value or "0.0"
    )

    try:
        whole, frac = text.split(".")
        return (
            int(whole) * 3
            + int(frac)
        )
    except Exception:
        return int(
            round(
                _float(value) * 3
            )
        )


def _hitter_actual(stat, prop):

    if prop == "hits":
        return _float(
            stat.get("hits")
        )

    if prop == "total_bases":
        return (
            _float(
                stat.get("totalBases")
            )
            or (
                _float(
                    stat.get("hits")
                )
                + _float(
                    stat.get("doubles")
                )
                + 2
                * _float(
                    stat.get("triples")
                )
                + 3
                * _float(
                    stat.get("homeRuns")
                )
            )
        )

    if prop == "home_runs":
        return _float(
            stat.get("homeRuns")
        )

    if prop == "walks":
        return _float(
            stat.get("baseOnBalls")
        )

    raise ValueError(prop)


def _pitcher_actual(stat, prop):

    if prop == "strikeouts":
        return _float(
            stat.get("strikeOuts")
        )

    if prop == "pitching_outs":
        return float(
            _innings_to_outs(
                stat.get(
                    "inningsPitched"
                )
            )
        )

    if prop == "hits_allowed":
        return _float(
            stat.get("hits")
        )

    if prop == "walks_allowed":
        return _float(
            stat.get("baseOnBalls")
        )

    if prop == "earned_runs":
        return _float(
            stat.get("earnedRuns")
        )

    raise ValueError(prop)


def _historical_hitter_projection(
    history,
    prop,
):
    """
    Strict walk-forward baseline.

    Only games before the target game are supplied.

    This intentionally measures the historical centering
    of the underlying player distribution before we add
    today's pitcher/Statcast information.
    """

    values = []

    for game in history[-20:]:

        stat = (
            game.get("stat")
            or {}
        )

        try:
            value = _hitter_actual(
                stat,
                prop,
            )
        except Exception:
            continue

        values.append(
            float(value)
        )

    if len(values) < 10:
        return None

    season_values = []

    for game in history:

        stat = (
            game.get("stat")
            or {}
        )

        try:
            season_values.append(
                float(
                    _hitter_actual(
                        stat,
                        prop,
                    )
                )
            )
        except Exception:
            pass

    if not season_values:
        return None

    season_mean = (
        sum(season_values)
        / len(season_values)
    )

    recent_mean = (
        sum(values)
        / len(values)
    )

    projection = (
        0.70 * season_mean
        + 0.30 * recent_mean
    )

    sigma = (
        statistics.pstdev(
            values
        )
        if len(values) >= 2
        else 0.0
    )

    return {
        "projection":
            projection,
        "sigma":
            sigma,
        "history_games":
            len(history),
    }


def _historical_pitcher_projection(
    history,
    prop,
):
    values = []

    for game in history[-20:]:

        stat = (
            game.get("stat")
            or {}
        )

        try:
            value = _pitcher_actual(
                stat,
                prop,
            )
        except Exception:
            continue

        values.append(
            float(value)
        )

    if len(values) < 8:
        return None

    season_values = []

    for game in history:

        stat = (
            game.get("stat")
            or {}
        )

        try:
            season_values.append(
                float(
                    _pitcher_actual(
                        stat,
                        prop,
                    )
                )
            )
        except Exception:
            pass

    if not season_values:
        return None

    season_mean = (
        sum(season_values)
        / len(season_values)
    )

    recent_mean = (
        sum(values)
        / len(values)
    )

    projection = (
        0.65 * season_mean
        + 0.35 * recent_mean
    )

    sigma = (
        statistics.pstdev(
            values
        )
        if len(values) >= 2
        else 0.0
    )

    return {
        "projection":
            projection,
        "sigma":
            sigma,
        "history_games":
            len(history),
    }


def walk_forward_player(
    player_name,
    season,
    player_type,
    prop,
    max_games=None,
):
    player = find_player(
        player_name
    )

    if not player:
        return []

    games = player_game_log(
        int(player["id"]),
        int(season),
        (
            "hitting"
            if player_type == "hitter"
            else "pitching"
        ),
    )

    if not games:
        return []

    minimum = (
        10
        if player_type == "hitter"
        else 8
    )

    rows = []

    start_index = minimum

    if max_games:
        start_index = max(
            minimum,
            len(games)
            - int(max_games),
        )

    for index in range(
        start_index,
        len(games),
    ):
        target = games[index]

        history = games[:index]

        stat = (
            target.get("stat")
            or {}
        )

        if player_type == "hitter":

            model = (
                _historical_hitter_projection(
                    history,
                    prop,
                )
            )

            actual = _hitter_actual(
                stat,
                prop,
            )

        else:

            model = (
                _historical_pitcher_projection(
                    history,
                    prop,
                )
            )

            actual = _pitcher_actual(
                stat,
                prop,
            )

        if model is None:
            continue

        projection = float(
            model["projection"]
        )

        actual = float(actual)

        error = (
            projection - actual
        )

        sigma = float(
            model.get("sigma")
            or 0.0
        )

        z_error = (
            error / sigma
            if sigma > 0
            else None
        )

        rows.append({
            "player":
                player_name,

            "date":
                target.get("date"),

            "opponent":
                target.get("opponent"),

            "projection":
                projection,

            "actual":
                actual,

            "error":
                error,

            "absolute_error":
                abs(error),

            "squared_error":
                error ** 2,

            "sigma":
                sigma,

            "z_error":
                z_error,

            "history_games":
                model[
                    "history_games"
                ],
        })

    return rows


def summarize(rows):

    if not rows:
        return None

    errors = [
        row["error"]
        for row in rows
    ]

    abs_errors = [
        row["absolute_error"]
        for row in rows
    ]

    sq_errors = [
        row["squared_error"]
        for row in rows
    ]

    actuals = [
        row["actual"]
        for row in rows
    ]

    projections = [
        row["projection"]
        for row in rows
    ]

    z_values = [
        row["z_error"]
        for row in rows
        if row["z_error"]
        is not None
    ]

    within_one_sigma = [
        row
        for row in rows
        if (
            row["sigma"] > 0
            and abs(
                row["error"]
            )
            <= row["sigma"]
        )
    ]

    within_two_sigma = [
        row
        for row in rows
        if (
            row["sigma"] > 0
            and abs(
                row["error"]
            )
            <= 2
            * row["sigma"]
        )
    ]

    return {
        "predictions":
            len(rows),

        "projection_mean":
            statistics.mean(
                projections
            ),

        "actual_mean":
            statistics.mean(
                actuals
            ),

        "mae":
            statistics.mean(
                abs_errors
            ),

        "rmse":
            math.sqrt(
                statistics.mean(
                    sq_errors
                )
            ),

        "bias":
            statistics.mean(
                errors
            ),

        "actual_sd":
            (
                statistics.pstdev(
                    actuals
                )
                if len(actuals) > 1
                else 0.0
            ),

        "mean_model_sigma":
            statistics.mean(
                row["sigma"]
                for row in rows
            ),

        "z_mean":
            (
                statistics.mean(
                    z_values
                )
                if z_values
                else None
            ),

        "z_sd":
            (
                statistics.pstdev(
                    z_values
                )
                if len(z_values) > 1
                else None
            ),

        "within_1_sigma":
            (
                len(
                    within_one_sigma
                )
                / len(rows)
            ),

        "within_2_sigma":
            (
                len(
                    within_two_sigma
                )
                / len(rows)
            ),
    }


def print_summary(
    player,
    season,
    player_type,
    prop,
    rows,
):

    result = summarize(
        rows
    )

    print()
    print("=" * 72)
    print(
        "MLB V2 WALK-FORWARD CALIBRATION"
    )
    print("=" * 72)

    print(
        "Player:",
        player,
    )

    print(
        "Season:",
        season,
    )

    print(
        "Type:",
        player_type,
    )

    print(
        "Prop:",
        prop,
    )

    print(
        "Market used: False"
    )

    print(
        "Historical PP lines used: False"
    )

    if not result:
        print(
            "No eligible historical games."
        )
        return

    print()
    print(
        "Predictions:",
        result[
            "predictions"
        ],
    )

    print(
        "Mean projection:",
        f'{result["projection_mean"]:.3f}',
    )

    print(
        "Mean actual:",
        f'{result["actual_mean"]:.3f}',
    )

    print(
        "Bias:",
        f'{result["bias"]:+.3f}',
    )

    print(
        "MAE:",
        f'{result["mae"]:.3f}',
    )

    print(
        "RMSE:",
        f'{result["rmse"]:.3f}',
    )

    print()
    print(
        "Actual SD:",
        f'{result["actual_sd"]:.3f}',
    )

    print(
        "Mean model sigma:",
        f'{result["mean_model_sigma"]:.3f}',
    )

    if (
        result["z_mean"]
        is not None
    ):
        print(
            "Z-error mean:",
            f'{result["z_mean"]:+.3f}',
        )

    if (
        result["z_sd"]
        is not None
    ):
        print(
            "Z-error SD:",
            f'{result["z_sd"]:.3f}',
        )

    print(
        "Actual within ±1 model sigma:",
        f'{result["within_1_sigma"]:.1%}',
    )

    print(
        "Actual within ±2 model sigma:",
        f'{result["within_2_sigma"]:.1%}',
    )

    print()
    print(
        "REFERENCE ONLY:"
    )

    print(
        "A roughly normal calibrated distribution "
        "would place about 68% inside ±1 sigma "
        "and about 95% inside ±2 sigma."
    )

    print()
    print(
        "This does NOT measure PrizePicks win rate."
    )

    print(
        "It measures historical centering and "
        "dispersion without look-ahead."
    )

    print()
    print(
        "LAST 10"
    )
    print("-" * 72)

    for row in rows[-10:]:

        print(
            f'{str(row["date"]):<12} '
            f'PROJ {row["projection"]:>6.2f} | '
            f'ACT {row["actual"]:>5.1f} | '
            f'ERR {row["error"]:>+6.2f} | '
            f'SD {row["sigma"]:>5.2f}'
        )


def main():

    parser = argparse.ArgumentParser(
        description=(
            "MLB V2 historical "
            "walk-forward calibration."
        )
    )

    parser.add_argument(
        "--player",
        required=True,
    )

    parser.add_argument(
        "--season",
        type=int,
        default=2026,
    )

    parser.add_argument(
        "--type",
        dest="player_type",
        required=True,
        choices=(
            "hitter",
            "pitcher",
        ),
    )

    parser.add_argument(
        "--prop",
        required=True,
    )

    parser.add_argument(
        "--max-games",
        type=int,
        default=20,
    )

    args = parser.parse_args()

    valid = (
        HITTER_PROPS
        if args.player_type
        == "hitter"
        else PITCHER_PROPS
    )

    if args.prop not in valid:
        raise SystemExit(
            "Valid props: "
            + ", ".join(valid)
        )

    rows = walk_forward_player(
        args.player,
        args.season,
        args.player_type,
        args.prop,
        max_games=args.max_games,
    )

    print_summary(
        args.player,
        args.season,
        args.player_type,
        args.prop,
        rows,
    )


if __name__ == "__main__":
    main()


# ============================================================
# MLB V2 POPULATION CALIBRATION
# ============================================================

def population_calibration(
    players,
    season,
    player_type,
    prop,
    max_games=20,
):
    all_rows = []
    by_player = []

    for player in players:

        try:
            rows = walk_forward_player(
                player,
                season,
                player_type,
                prop,
                max_games=max_games,
            )
        except Exception as exc:
            print(
                "SKIP:",
                player,
                "-",
                exc,
            )
            continue

        if not rows:
            print(
                "SKIP:",
                player,
                "- no eligible games",
            )
            continue

        result = summarize(
            rows
        )

        if not result:
            continue

        all_rows.extend(
            rows
        )

        by_player.append({
            "player":
                player,
            "n":
                result[
                    "predictions"
                ],
            "projection":
                result[
                    "projection_mean"
                ],
            "actual":
                result[
                    "actual_mean"
                ],
            "bias":
                result[
                    "bias"
                ],
            "mae":
                result[
                    "mae"
                ],
            "rmse":
                result[
                    "rmse"
                ],
            "sigma":
                result[
                    "mean_model_sigma"
                ],
        })

    overall = summarize(
        all_rows
    )

    return {
        "rows":
            all_rows,
        "players":
            by_player,
        "overall":
            overall,
    }


def print_population_calibration(
    title,
    result,
):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)

    overall = result.get(
        "overall"
    )

    if not overall:
        print(
            "No eligible population results."
        )
        return

    print(
        "Players:",
        len(
            result["players"]
        ),
    )

    print(
        "Predictions:",
        overall[
            "predictions"
        ],
    )

    print(
        "Mean projection:",
        f'{overall["projection_mean"]:.3f}',
    )

    print(
        "Mean actual:",
        f'{overall["actual_mean"]:.3f}',
    )

    print(
        "BIAS:",
        f'{overall["bias"]:+.3f}',
    )

    print(
        "MAE:",
        f'{overall["mae"]:.3f}',
    )

    print(
        "RMSE:",
        f'{overall["rmse"]:.3f}',
    )

    print(
        "Actual SD:",
        f'{overall["actual_sd"]:.3f}',
    )

    print(
        "Mean model sigma:",
        f'{overall["mean_model_sigma"]:.3f}',
    )

    print(
        "Within ±1 sigma:",
        f'{overall["within_1_sigma"]:.1%}',
    )

    print(
        "Within ±2 sigma:",
        f'{overall["within_2_sigma"]:.1%}',
    )

    print()
    print(
        "PLAYER BREAKDOWN"
    )

    print("-" * 78)

    print(
        f'{"PLAYER":<24}'
        f'{"N":>4}'
        f'{"PROJ":>9}'
        f'{"ACT":>9}'
        f'{"BIAS":>9}'
        f'{"MAE":>9}'
    )

    for row in sorted(
        result["players"],
        key=lambda x: x["bias"],
        reverse=True,
    ):
        print(
            f'{row["player"]:<24}'
            f'{row["n"]:>4}'
            f'{row["projection"]:>9.3f}'
            f'{row["actual"]:>9.3f}'
            f'{row["bias"]:>+9.3f}'
            f'{row["mae"]:>9.3f}'
        )

    biases = [
        row["bias"]
        for row in result[
            "players"
        ]
    ]

    positive = sum(
        1
        for value in biases
        if value > 0
    )

    negative = sum(
        1
        for value in biases
        if value < 0
    )

    print()
    print(
        "Players with positive bias:",
        positive,
    )

    print(
        "Players with negative bias:",
        negative,
    )

    if biases:
        print(
            "Median player bias:",
            f'{statistics.median(biases):+.3f}',
        )

    print()
    print(
        "Market used: False"
    )

    print(
        "Historical PP lines used: False"
    )

    print(
        "No calibration correction "
        "has been applied."
    )
