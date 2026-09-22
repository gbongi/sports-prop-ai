import os
import re
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone

import requests

from propline_market import build_market_consensus, compare_model_to_market

PROPLINE_BASE_URL = "https://api.prop-line.com/v1"
PROPLINE_SPORT = "basketball_wnba"
CACHE_SECONDS = 600
_CACHE = {}
MIN_BOOKS = 3

WNBA_MARKET_MAP = {
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "3pm": "player_threes",
    "pr": "player_points_rebounds",
    "pa": "player_points_assists",
    "ra": "player_rebounds_assists",
    "pra": "player_points_rebounds_assists",
}

WNBA_TEAM_ALIASES = {
    "ATL":"Atlanta Dream", "CHI":"Chicago Sky", "CON":"Connecticut Sun", "CT":"Connecticut Sun",
    "DAL":"Dallas Wings", "GS":"Golden State Valkyries", "GSV":"Golden State Valkyries",
    "IND":"Indiana Fever", "LA":"Los Angeles Sparks", "LAS":"Las Vegas Aces", "LV":"Las Vegas Aces",
    "MIN":"Minnesota Lynx", "NY":"New York Liberty", "NYL":"New York Liberty", "PHX":"Phoenix Mercury",
    "SEA":"Seattle Storm", "WAS":"Washington Mystics", "WSH":"Washington Mystics",
    "POR":"Portland Fire", "TOR":"Toronto Tempo",
}

def _norm(v):
    if not v: return ""
    v=unicodedata.normalize("NFKD", str(v).strip().lower())
    v="".join(c for c in v if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", v)

def _team(v):
    raw=str(v or '').strip()
    return WNBA_TEAM_ALIASES.get(raw.upper(), raw)

def _parse_time(v):
    if not v: return None
    try:
        v=str(v).replace('Z','+00:00')
        return datetime.fromisoformat(v)
    except Exception: return None

def _events_list(data):
    if isinstance(data, list): return data
    if isinstance(data, dict):
        for key in ('data','events'):
            if isinstance(data.get(key), list): return data[key]
    return []

def get_wnba_events(force_refresh=False):
    key=os.getenv('PROPLINE_API_KEY')
    if not key: raise RuntimeError('PROPLINE_API_KEY is not loaded in the environment.')
    ck=('wnba_events',); now=time.time()
    if not force_refresh and ck in _CACHE and now-_CACHE[ck][0] < CACHE_SECONDS: return _CACHE[ck][1]
    r=requests.get(f'{PROPLINE_BASE_URL}/sports/{PROPLINE_SPORT}/events', headers={'X-API-Key':key}, timeout=30)
    r.raise_for_status()
    out={'data':r.json(),'usage':{'daily_limit':r.headers.get('X-Daily-Limit'),'daily_used':r.headers.get('X-Daily-Used'),'daily_remaining':r.headers.get('X-Daily-Remaining')}}
    _CACHE[ck]=(now,out); return out

def get_wnba_event_odds(event_id, markets, force_refresh=False):
    key=os.getenv('PROPLINE_API_KEY')
    if not key: raise RuntimeError('PROPLINE_API_KEY is not loaded in the environment.')
    markets=sorted(set(markets)); ck=('wnba_odds',str(event_id),tuple(markets)); now=time.time()
    if not force_refresh and ck in _CACHE and now-_CACHE[ck][0] < CACHE_SECONDS: return _CACHE[ck][1]
    r=requests.get(f'{PROPLINE_BASE_URL}/sports/{PROPLINE_SPORT}/events/{event_id}/odds', headers={'X-API-Key':key}, params={'markets':','.join(markets)}, timeout=30)
    r.raise_for_status(); data=r.json(); _CACHE[ck]=(now,data); return data


def _wnba_team_canonical(value):
    """
    Convert PrizePicks full franchise names, PropLine city names,
    nicknames, and PropLine team keys to one canonical identifier.
    """
    value = _norm(value)

    aliases = {
        # Atlanta
        "atlantadream": "atlantadream",
        "atl": "atlantadream",
        "atlanta": "atlantadream",
        "dream": "atlantadream",

        # Chicago
        "chicagosky": "chicagosky",
        "chi": "chicagosky",
        "chicago": "chicagosky",
        "sky": "chicagosky",

        # Connecticut
        "connecticutsun": "connecticutsun",
        "con": "connecticutsun",
        "connecticut": "connecticutsun",
        "sun": "connecticutsun",
        "sunwnba": "connecticutsun",

        # Dallas
        "dallaswings": "dallaswings",
        "dal": "dallaswings",
        "dallas": "dallaswings",
        "wings": "dallaswings",

        # Golden State
        "goldenstatevalkyries": "goldenstatevalkyries",
        "gsv": "goldenstatevalkyries",
        "goldenstate": "goldenstatevalkyries",
        "valkyries": "goldenstatevalkyries",

        # Indiana
        "indianafever": "indianafever",
        "ind": "indianafever",
        "indiana": "indianafever",
        "fever": "indianafever",

        # Las Vegas
        "lasvegasaces": "lasvegasaces",
        "lv": "lasvegasaces",
        "lva": "lasvegasaces",
        "lasvegas": "lasvegasaces",
        "aces": "lasvegasaces",

        # Los Angeles
        "losangelessparks": "losangelessparks",
        "la": "losangelessparks",
        "las": "losangelessparks",
        "losangeles": "losangelessparks",
        "sparks": "losangelessparks",

        # Minnesota
        "minnesotalynx": "minnesotalynx",
        "min": "minnesotalynx",
        "minnesota": "minnesotalynx",
        "lynx": "minnesotalynx",

        # New York
        "newyorkliberty": "newyorkliberty",
        "ny": "newyorkliberty",
        "nyl": "newyorkliberty",
        "newyork": "newyorkliberty",
        "liberty": "newyorkliberty",

        # Phoenix
        "phoenixmercury": "phoenixmercury",
        "phx": "phoenixmercury",
        "phoenix": "phoenixmercury",
        "mercury": "phoenixmercury",

        # Portland
        "portlandfire": "portlandfire",
        "por": "portlandfire",
        "portland": "portlandfire",
        "fire": "portlandfire",

        # Seattle
        "seattlestorm": "seattlestorm",
        "sea": "seattlestorm",
        "seattle": "seattlestorm",
        "storm": "seattlestorm",

        # Toronto
        "torontotempo": "torontotempo",
        "tor": "torontotempo",
        "toronto": "torontotempo",
        "tempo": "torontotempo",

        # Washington
        "washingtonmystics": "washingtonmystics",
        "was": "washingtonmystics",
        "wsh": "washingtonmystics",
        "washington": "washingtonmystics",
        "mystics": "washingtonmystics",
    }

    return aliases.get(value, value)


def _wnba_event_side(event, side):
    """
    Prefer PropLine's stable team key when present.
    Fall back to its display name.
    """
    key = event.get(f"{side}_team_key")
    name = event.get(f"{side}_team")

    if key:
        canonical = _wnba_team_canonical(key)
        if canonical:
            return canonical

    return _wnba_team_canonical(name)


def _wnba_utc_time(value):
    if not value:
        return None

    text = str(value).strip()

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def find_wnba_event(away, home, start_time, events):
    """
    Safely match a PrizePicks game to one PropLine event.

    Match requirements:
      - away franchise
      - home franchise
      - start time when available

    Never guess between ambiguous events.
    """

    target_away = _wnba_team_canonical(away)
    target_home = _wnba_team_canonical(home)
    target_time = _wnba_utc_time(start_time)

    matches = []

    for event in _events_list(events):

        event_away = _wnba_event_side(event, "away")
        event_home = _wnba_event_side(event, "home")

        if event_away != target_away:
            continue

        if event_home != target_home:
            continue

        event_time = _wnba_utc_time(
            event.get("commence_time")
        )

        time_difference = None

        if target_time is not None and event_time is not None:
            time_difference = abs(
                (event_time - target_time).total_seconds()
            )

            # PrizePicks and PropLine should normally agree exactly.
            # 30 minutes allows small provider schedule differences.
            if time_difference > 1800:
                continue

        matches.append(
            (time_difference, event)
        )

    if not matches:
        return {
            "matched": False,
            "reason": "EVENT_NOT_FOUND",
            "target_away": target_away,
            "target_home": target_home,
            "start_time": start_time,
        }

    if len(matches) > 1:

        timed = [
            x for x in matches
            if x[0] is not None
        ]

        if not timed:
            return {
                "matched": False,
                "reason": "MULTIPLE_EVENT_MATCHES",
            }

        timed.sort(key=lambda x: x[0])

        if (
            len(timed) > 1
            and timed[0][0] == timed[1][0]
        ):
            return {
                "matched": False,
                "reason": "AMBIGUOUS_EVENT_TIME",
            }

        difference, event = timed[0]

    else:
        difference, event = matches[0]

    event_id = event.get("id")

    if event_id is None:
        return {
            "matched": False,
            "reason": "EVENT_ID_MISSING",
            "event": event,
        }

    return {
        "matched": True,
        "event_id": str(event_id),
        "away_team": event.get("away_team"),
        "home_team": event.get("home_team"),
        "away_team_key": event.get("away_team_key"),
        "home_team_key": event.get("home_team_key"),
        "commence_time": event.get("commence_time"),
        "time_difference_seconds": difference,
        "event": event,
    }


def enrich_wnba_pp_board_with_market(pp_rows, force_refresh=False):
    prepared=[]; skipped=[]
    for row in pp_rows:
        prop=row.get('model_prop') or row.get('prop')
        if prop not in WNBA_MARKET_MAP:
            skipped.append({'row':row,'market_available':False,'market_reason':'MARKET_UNSUPPORTED'}); continue
        try: line=float(row.get('line'))
        except (TypeError,ValueError):
            skipped.append({'row':row,'market_available':False,'market_reason':'PP_LINE_MISSING'}); continue
        away=row.get('away_team') or row.get('away'); home=row.get('home_team') or row.get('home'); start=row.get('start_time') or row.get('game_start_time')
        if not away or not home or not start:
            skipped.append({'row':row,'market_available':False,'market_reason':'GAME_INFO_MISSING'}); continue
        prepared.append({'row':row,'prop':prop,'market':WNBA_MARKET_MAP[prop],'line':line,'away':away,'home':home,'start':start,'key':(_norm(_team(away)),_norm(_team(home)),str(start))})
    if not prepared: return {'rows':[],'skipped':skipped,'games':0,'matched_games':0,'market_requests':0,'errors':[]}
    groups=defaultdict(list)
    for x in prepared: groups[x['key']].append(x)
    wrapper=get_wnba_events(force_refresh=force_refresh); events=wrapper.get('data',[])
    output=[]; errors=[]; matched=0; requests_count=0
    for key, rows in groups.items():
        s=rows[0]; match=find_wnba_event(s['away'],s['home'],s['start'],events)
        if not match.get('matched'):
            errors.append({'game_key':key,'reason':match.get('reason')})
            for x in rows:
                b=dict(x['row']); b.update({'market_available':False,'market_reason':match.get('reason'),'market_strength':'UNAVAILABLE','market_books':0}); output.append(b)
            continue
        matched += 1
        try:
            data=get_wnba_event_odds(match['event_id'], [x['market'] for x in rows], force_refresh=force_refresh); requests_count += 1
        except Exception as exc:
            errors.append({'game_key':key,'reason':'PROPLINE_REQUEST_FAILED','error':str(exc)})
            for x in rows:
                b=dict(x['row']); b.update({'market_available':False,'market_reason':'PROPLINE_REQUEST_FAILED','market_strength':'UNAVAILABLE','market_books':0}); output.append(b)
            continue
        for x in rows:
            c=build_market_consensus(data, x['row'].get('player'), x['market'], x['line'])
            b=dict(x['row'])
            b.update({'pp_line':x['line'],'market_available':bool(c.get('available')),'market_reason':c.get('reason'),'market_lean':c.get('market_lean'),'market_probability':c.get('market_probability'),'market_more_probability':c.get('market_more_probability'),'market_less_probability':c.get('market_less_probability'),'market_strength':c.get('market_strength','UNAVAILABLE'),'market_books':c.get('books_at_exact_line',0),'market_dispersion':c.get('market_dispersion'),'market_outliers_removed':len(c.get('outliers_removed',[])),'propline_event_id':match['event_id']})
            output.append(b)
    return {'rows':output,'skipped':skipped,'games':len(groups),'matched_games':matched,'market_requests':requests_count,'errors':errors,'usage':wrapper.get('usage',{})}
