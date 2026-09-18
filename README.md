# WNBA Prop AI

Starter project for data-driven WNBA MORE/LESS/PASS analysis.

## Current pieces
- SQLite database for player games, injury snapshots, prop-line snapshots, and predictions.
- Derived PRA, RA, PA, and PR calculations.
- Baseline and streak utilities.
- Placeholders for official WNBA game, schedule, injury, and matchup ingestion.

## Run
```bash
python3 main.py
```

The next development step is connecting verified official WNBA/NBA data sources and loading real historical games into `database/wnba.db`.
