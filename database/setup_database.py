import sqlite3
from pathlib import Path

DATABASE_PATH = Path(__file__).parent / 'wnba.db'


def create_database():
    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            date TEXT NOT NULL,
            season INTEGER NOT NULL,
            player_id TEXT NOT NULL,
            player TEXT NOT NULL,
            team TEXT NOT NULL,
            opponent TEXT NOT NULL,
            home_away TEXT,
            minutes REAL,
            starter INTEGER,
            days_rest INTEGER,
            points INTEGER,
            rebounds INTEGER,
            assists INTEGER,
            three_pm INTEGER,
            steals INTEGER,
            blocks INTEGER,
            turnovers INTEGER,
            fg_made INTEGER,
            fg_attempts INTEGER,
            three_pa INTEGER,
            ft_made INTEGER,
            ft_attempts INTEGER,
            offensive_rebounds INTEGER,
            defensive_rebounds INTEGER,
            personal_fouls INTEGER,
            plus_minus REAL,
            UNIQUE(game_id, player_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS injuries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            player_id TEXT,
            player TEXT NOT NULL,
            team TEXT,
            status TEXT,
            injury TEXT,
            source TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prop_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            game_id TEXT,
            player_id TEXT,
            player TEXT NOT NULL,
            prop_type TEXT NOT NULL,
            line REAL NOT NULL,
            platform TEXT,
            UNIQUE(captured_at, player, prop_type, platform)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            game_id TEXT,
            player_id TEXT,
            player TEXT NOT NULL,
            prop_type TEXT NOT NULL,
            line REAL NOT NULL,
            projection REAL,
            probability_more REAL,
            probability_less REAL,
            lean TEXT,
            notes TEXT
        )
    ''')

    connection.commit()
    connection.close()
    print('WNBA database created successfully!')
    print(f'Database location: {DATABASE_PATH}')


if __name__ == '__main__':
    create_database()
