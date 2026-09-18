#!/usr/bin/env python3

"""
Walk-forward WNBA projection backtester.

This tests the V1 projection engine without look-ahead:
for each target game, only earlier games for that player are used.

This first version evaluates projection quality (MAE/RMSE/bias).
It does NOT claim true MORE/LESS betting accuracy because historical
pregame prop lines are not yet stored in the project.
"""

import argparse
import math
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

from main import get_stat, predict_prop_v1, DATABASE

VALID_PROPS = (
    "points",
    "rebounds",
    "assists",
    "3pm",
    "pra",
    "ra",
    "pa",
    "pr",
)

MIN_HISTORY = 10


def get_players(season):
    connection = sqlite3.connect(DATABASE)
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT DISTINCT player
        FROM player_games
        WHERE season = ?
        AND player IS NOT NULL
        ORDER BY player
        """,
        (season,)
    )

    players = [
        row[0]
        for row in cursor.fetchall()
    ]

    connection.close()
    return players


def get_exact_player_games(player, season):
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT *
        FROM player_games
        WHERE LOWER(player) = LOWER(?)
        AND season = ?
        ORDER BY date ASC, id ASC
        """,
        (player, season)
    )

    games = cursor.fetchall()
    connection.close()
    return games


def walk_forward_player(player, season, prop):
    games = get_exact_player_games(player, season)

    rows = []

    for index in range(MIN_HISTORY, len(games)):

        target_game = games[index]
        actual = get_stat(target_game, prop)

        if actual is None:
            continue

        history = games[:index]

        # We deliberately pass the actual upcoming opponent because
        # opponent identity is known pregame. predict_prop_v1 only
        # searches the historical slice supplied here.
        opponent = target_game["opponent"]

        # The V1 function requires a line to compute probabilities.
        # For projection-error testing, the line does not affect the
        # projection itself, so use 0.0 and ignore P(MORE)/P(LESS).
        prediction = predict_prop_v1(
            history,
            prop,
            0.0,
            opponent
        )

        if prediction is None:
            continue

        projected = float(
            prediction["projection"]
        )

        actual = float(actual)
        error = projected - actual

        rows.append(
            {
                "player": player,
                "date": target_game["date"],
                "opponent": opponent,
                "projection": projected,
                "actual": actual,
                "error": error,
                "absolute_error": abs(error),
                "squared_error": error ** 2,
            }
        )

    return rows


def summarize(rows):
    if not rows:
        return None

    errors = [
        row["error"]
        for row in rows
    ]

    absolute_errors = [
        row["absolute_error"]
        for row in rows
    ]

    squared_errors = [
        row["squared_error"]
        for row in rows
    ]

    return {
        "predictions": len(rows),
        "mae": statistics.mean(absolute_errors),
        "rmse": math.sqrt(
            statistics.mean(squared_errors)
        ),
        "bias": statistics.mean(errors),
    }


def run_backtest(season, prop, player=None):
    if prop not in VALID_PROPS:
        raise ValueError(
            "Unknown prop. Valid props: "
            + ", ".join(VALID_PROPS)
        )

    if player:
        players = [player]
    else:
        players = get_players(season)

    all_rows = []
    player_rows = defaultdict(list)

    for name in players:
        rows = walk_forward_player(
            name,
            season,
            prop
        )

        if rows:
            all_rows.extend(rows)
            player_rows[name].extend(rows)

    result = summarize(all_rows)

    print()
    print("=" * 68)
    print("WNBA WALK-FORWARD PROJECTION BACKTEST")
    print("=" * 68)
    print("Season:", season)
    print("Prop:", prop.upper())
    print("Minimum prior games:", MIN_HISTORY)
    print("Players tested:", len(player_rows))

    if result is None:
        print("No eligible predictions.")
        return

    print("Predictions:", result["predictions"])
    print()
    print(
        "MAE:",
        f"{result['mae']:.3f}"
    )
    print(
        "RMSE:",
        f"{result['rmse']:.3f}"
    )
    print(
        "BIAS:",
        f"{result['bias']:+.3f}"
    )

    print()
    print("INTERPRETATION")
    print("-" * 68)
    print(
        "MAE  = average absolute difference between projection and actual."
    )
    print(
        "RMSE = penalizes larger misses more heavily."
    )
    print(
        "BIAS = positive means projections run high; negative means low."
    )
    print()
    print(
        "This is a projection backtest only. It does not report betting "
        "win rate because historical pregame prop lines are not yet used."
    )

    if player and all_rows:
        print()
        print("LAST 10 WALK-FORWARD PREDICTIONS")
        print("-" * 68)

        for row in all_rows[-10:]:
            print(
                f"{row['date']} vs {row['opponent']:<4} "
                f"PROJ {row['projection']:>6.2f} | "
                f"ACTUAL {row['actual']:>5.1f} | "
                f"ERROR {row['error']:>+6.2f}"
            )


def main():
    parser = argparse.ArgumentParser(
        description="Walk-forward WNBA projection backtester."
    )

    parser.add_argument(
        "--season",
        type=int,
        default=2026
    )

    parser.add_argument(
        "--prop",
        required=True,
        choices=VALID_PROPS
    )

    parser.add_argument(
        "--player",
        default=None
    )

    args = parser.parse_args()

    run_backtest(
        args.season,
        args.prop,
        args.player
    )


if __name__ == "__main__":
    main()
