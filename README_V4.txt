MLB PROBABLE PITCHERS V4

NEW:
When Sport=MLB and Team + Opponent are selected, the page automatically checks
today's MLB matchup and displays:

- YOUR TEAM'S PROBABLE STARTER
- OPPONENT'S PROBABLE STARTER
- Away @ Home matchup
- Game status

No pitcher name needs to be typed.

HARD DATA RULE:
If the probable pitcher has not been posted, the site displays DATA UNAVAILABLE.
It does NOT guess a pitcher and does NOT create a fake pitcher adjustment.

The analysis engine continues using the opponent's posted probable starter as the
hitter matchup context when available.

INSTALL:
cd ~/Downloads
unzip -o sports_prop_ai_probable_pitchers_v4.zip -d sports_prop_v4
cp sports_prop_v4/main.py ~/sports_prop_ai/main.py
cp sports_prop_v4/mlb_model.py ~/sports_prop_ai/mlb_model.py
cp sports_prop_v4/app.py ~/sports_prop_ai/app.py
cp -R sports_prop_v4/templates ~/sports_prop_ai/
cp -R sports_prop_v4/static ~/sports_prop_ai/
cd ~/sports_prop_ai
python3 -m py_compile main.py mlb_model.py app.py
python3 app.py
