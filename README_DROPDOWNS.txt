TEAM / PLAYER / OPPONENT DROPDOWN UPDATE

Adds dependent dropdowns for BOTH WNBA and MLB:
Sport -> Team -> Player -> Opponent -> Prop.

MLB:
- Active roster is loaded from MLB's public Stats API.
- Hitter/Pitcher selection filters the roster.
- Today's matching game context shows probable starting pitchers when posted.
- Opponent is selected by team dropdown.

WNBA:
- Team and player dropdowns come from your existing 2026 player_games database.
- Opponent uses the same team list.
- Existing WNBA prediction engine remains intact.

INSTALL:
cd ~/Downloads
unzip -o sports_prop_ai_dropdown_update.zip -d sports_prop_dropdown
cp sports_prop_dropdown/main.py ~/sports_prop_ai/main.py
cp sports_prop_dropdown/mlb_model.py ~/sports_prop_ai/mlb_model.py
cp sports_prop_dropdown/app.py ~/sports_prop_ai/app.py
cp -R sports_prop_dropdown/templates ~/sports_prop_ai/
cp -R sports_prop_dropdown/static ~/sports_prop_ai/
cd ~/sports_prop_ai
python3 -m py_compile main.py mlb_model.py app.py
python3 app.py
