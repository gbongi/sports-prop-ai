SPORTS PROP AI — COMBINED WNBA + MLB

This keeps WNBA and MLB as separate prediction engines behind one website.

INSTALL / REPLACE
1) Extract the ZIP.
2) Copy these files into ~/sports_prop_ai
3) Keep your existing data/ and database/ directories.
4) Run:

cd ~/sports_prop_ai
python3 -m py_compile main.py mlb_model.py app.py
python3 app.py

Then open http://127.0.0.1:5000

UI
- Sport dropdown: WNBA / MLB
- WNBA uses the existing WNBA engine.
- MLB reveals Hitter / Pitcher.
- The browser remembers the last selected sport.

MLB HITTER PROPS
hits, total bases, runs, RBI, walks, home runs, hitter fantasy score

MLB PITCHER PROPS
strikeouts, pitching outs, hits allowed, walks allowed, earned runs, pitcher fantasy score

IMPORTANT MODEL NOTE
The first MLB engine deliberately does NOT fabricate lineup, weather, park, handedness,
or injury effects. It retrieves MLB game logs at runtime and uses a regressed multi-horizon
baseline + small H2H support + a count distribution. The next MLB upgrade should add
verified pregame starter/lineup/park/weather/handedness inputs and then backtest them.
