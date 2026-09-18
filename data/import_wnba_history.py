import sqlite3
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
DATABASE = ROOT / "database" / "wnba.db"

BASE_URL = (
    "https://github.com/sportsdataverse/"
    "sportsdataverse-data/releases/download/"
    "espn_wnba_player_boxscores/"
    "player_box_{season}.csv"
)


def safe_int(value):
    if pd.isna(value):
        return None
    return int(value)


def safe_float(value):
    if pd.isna(value):
        return None

    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def download_season(season):
    url = BASE_URL.format(season=season)

    print(f"\nDownloading WNBA {season}...")

    try:
        df = pd.read_csv(url)
        print(f"Downloaded {len(df):,} player-game rows.")
        return df

    except Exception as error:
        print(f"Could not download {season}:")
        print(error)
        return None


def calculate_days_rest(df):
    df["game_date"] = pd.to_datetime(df["game_date"])

    df = df.sort_values(
        ["athlete_id", "game_date"]
    )

    df["previous_game"] = (
        df.groupby("athlete_id")["game_date"].shift(1)
    )

    df["days_rest"] = (
        df["game_date"] - df["previous_game"]
    ).dt.days - 1

    return df


def import_season(season):

    df = download_season(season)

    if df is None or df.empty:
        return

    # Remove players who did not actually play
    if "did_not_play" in df.columns:
        df = df[df["did_not_play"] != True].copy()

    df = calculate_days_rest(df)

    connection = sqlite3.connect(DATABASE)
    cursor = connection.cursor()

    inserted = 0
    skipped = 0

    for _, row in df.iterrows():

        try:

            cursor.execute(
                """
                INSERT OR REPLACE INTO player_games (

                    game_id,
                    date,
                    season,

                    player_id,
                    player,

                    team,
                    opponent,
                    home_away,

                    minutes,
                    starter,
                    days_rest,

                    points,
                    rebounds,
                    assists,
                    three_pm,

                    steals,
                    blocks,
                    turnovers,

                    fg_made,
                    fg_attempts,
                    three_pa,

                    ft_made,
                    ft_attempts,

                    offensive_rebounds,
                    defensive_rebounds,

                    personal_fouls,
                    plus_minus

                )

                VALUES (
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?
                )
                """,

                (
                    str(row["game_id"]),
                    str(row["game_date"].date()),
                    int(row["season"]),

                    str(row["athlete_id"]),
                    row["athlete_display_name"],

                    row["team_abbreviation"],
                    row["opponent_team_abbreviation"],
                    str(row["home_away"]).upper(),

                    safe_float(row["minutes"]),
                    int(bool(row["starter"])),
                    safe_int(row["days_rest"]),

                    safe_int(row["points"]),
                    safe_int(row["rebounds"]),
                    safe_int(row["assists"]),
                    safe_int(
                        row["three_point_field_goals_made"]
                    ),

                    safe_int(row["steals"]),
                    safe_int(row["blocks"]),
                    safe_int(row["turnovers"]),

                    safe_int(row["field_goals_made"]),
                    safe_int(row["field_goals_attempted"]),

                    safe_int(
                        row[
                            "three_point_field_goals_attempted"
                        ]
                    ),

                    safe_int(row["free_throws_made"]),
                    safe_int(row["free_throws_attempted"]),

                    safe_int(row["offensive_rebounds"]),
                    safe_int(row["defensive_rebounds"]),

                    safe_int(row["fouls"]),
                    safe_float(row["plus_minus"]),
                )
            )

            inserted += 1

        except Exception as error:

            skipped += 1

            print(
                "Skipped:",
                row.get("athlete_display_name"),
                error
            )

    connection.commit()
    connection.close()

    print()
    print("=" * 55)
    print(f"{season} IMPORT COMPLETE")
    print("=" * 55)

    print("Inserted:", inserted)
    print("Skipped:", skipped)


if __name__ == "__main__":

    seasons = [
        2020,
        2021,
        2022,
        2023,
        2024,
        2025,
        2026,
    ]

    for season in seasons:
        import_season(season)