MLB VERIFIED PREGAME V3

HARD RULE:
If MLB has not posted a confirmed batting order, the program does NOT guess it.
It displays DATA UNAVAILABLE and applies NO lineup adjustment.

This version adds:
- confirmed batting order detection from MLB game live-feed
- opposing probable/announced starter
- batter/pitcher handedness
- recent expected plate appearances for hitters
- recent expected pitching outs for pitchers
- venue/park
- game-feed weather when available
- explicit DATA UNAVAILABLE state for missing information
- projection audit: before adjustment, verified multiplier, after adjustment

Conservative rules:
- Missing data = neutral multiplier (1.00), never a guessed penalty/boost.
- Batting-order opportunity adjustment only runs when an actual MLB battingOrder exists.
- Handedness is displayed, but no split multiplier is applied until a verified split source is wired and backtested.
- Injury adjustment remains neutral until a reliable injury feed is wired.
- Weather remains neutral when unavailable; this version displays verified feed weather but does not apply an unbacktested weather multiplier.

INSTALL
cd ~/Downloads
unzip -o sports_prop_ai_mlb_pregame_v3.zip -d sports_prop_pregame
cp sports_prop_pregame/main.py ~/sports_prop_ai/main.py
cp sports_prop_pregame/mlb_model.py ~/sports_prop_ai/mlb_model.py
cp sports_prop_pregame/app.py ~/sports_prop_ai/app.py
cp -R sports_prop_pregame/templates ~/sports_prop_ai/
cp -R sports_prop_pregame/static ~/sports_prop_ai/
cd ~/sports_prop_ai
python3 -m py_compile main.py mlb_model.py app.py
python3 app.py
