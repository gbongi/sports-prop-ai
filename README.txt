WNBA V2 FULL UPDATE

1. Extract this bundle.
2. Copy main.py, app.py, templates, and static into ~/sports_prop_ai.
3. Keep your existing database/ and data/ folders.
4. Run:
   cd ~/sports_prop_ai
   python3 -m py_compile main.py app.py
   python3 app.py

This version adds:
- expected minutes from season + recent role
- conservative teammate OUT/DOUBTFUL opportunity bump
- opponent team scoring/rebounding/assist environment
- opponent FG% allowed and missed-shot environment in CLI
- H2H remains small/shrunk
- existing injury display
- existing blowout adjustment
- projection comparison on website

Important:
The current DB does not contain reliable position/tracking assignments, so the code does not fabricate
position-specific defense or likely individual defensive assignments.
