"""
MLB V2 PrizePicks Adapter

PrizePicks supplies:
    player
    prop
    line

Baseball model supplies:
    projection
    simulated distribution
    P(MORE)
    P(LESS)
    PUSH
    direction
    MORE / LESS / PASS

PrizePicks line NEVER changes the baseball projection.
Market data is NOT used here.
"""

from mlb_model import verified_pregame_context
from mlb_simulator_v2 import (
    simulate_hitter_matchup_full,
    simulate_pitcher_matchup_full,
    simulated_prop_result,
)


HITTER_PROP_MAP = {
    "hits": "hits",
    "total_bases": "total_bases",
    "runs": "runs",
    "rbi": "rbi",
    "walks": "walks",
    "home_runs": "home_runs",
    "hitter_fantasy_score": "hitter_fantasy_score",
}

PITCHER_PROP_MAP = {
    "strikeouts": "strikeouts",
    "pitching_outs": "pitching_outs",
    "hits_allowed": "hits_allowed",
    "walks_allowed": "walks_allowed",
    "earned_runs": "earned_runs",
    "pitcher_fantasy_score": "pitcher_fantasy_score",
}


def _clean_prop(value):
    return str(value or "").strip().lower()


def _readiness_from_pregame(
    player_type,
    pregame,
):
    if player_type == "hitter":
        if (
            pregame.get("lineup") == "confirmed"
            and pregame.get("in_starting_lineup") is False
        ):
            return "PASS_NOT_IN_LINEUP"

        if (
            pregame.get("lineup") != "confirmed"
            or pregame.get("in_starting_lineup") is not True
        ):
            return "PREGAME_PENDING"

        if not pregame.get("starter_name"):
            return "PREGAME_PENDING"

        return "BASEBALL_CONTEXT_READY"

    if player_type == "pitcher":
        if not pregame.get("starter_name"):
            return "PREGAME_PENDING"

        return "PREGAME_PENDING"

    return "PREGAME_PENDING"


def analyze_v2_prizepicks_row(
    player_name,
    player_type,
    model_prop,
    line,
    team_id,
    opponent_id,
    opponent_name=None,
    season=2026,
    simulations=1000,
    seed=20260924,
):
    player_type = str(
        player_type or ""
    ).strip().lower()

    model_prop = _clean_prop(
        model_prop
    )

    line = float(line)

    pregame = verified_pregame_context(
        player_name,
        player_type,
        int(team_id),
        int(opponent_id),
        season=season,
    )

    readiness = _readiness_from_pregame(
        player_type,
        pregame,
    )

    if readiness == "PASS_NOT_IN_LINEUP":
        return {
            "available": True,
            "model_version": "MLB_V2_SIM_0.2",
            "player": player_name,
            "player_type": player_type,
            "model_prop": model_prop,
            "line": line,
            "projection": None,
            "p_more": None,
            "p_less": None,
            "p_push": None,
            "model_direction": None,
            "lean": "PASS",
            "qualifies": False,
            "confidence": "PASS",
            "readiness": readiness,
            "pregame": pregame,
            "market_used": False,
            "reason": "Player is not in confirmed starting lineup.",
        }

    if player_type == "hitter":
        stat_key = HITTER_PROP_MAP.get(
            model_prop
        )

        if not stat_key:
            raise ValueError(
                f"Unsupported V2 hitter prop: {model_prop}"
            )

        pitcher_name = pregame.get(
            "starter_name"
        )

        if not pitcher_name:
            return {
                "available": False,
                "player": player_name,
                "player_type": player_type,
                "model_prop": model_prop,
                "line": line,
                "lean": "PASS",
                "qualifies": False,
                "confidence": "PASS",
                "readiness": "PREGAME_PENDING",
                "pregame": pregame,
                "market_used": False,
                "reason": "Opposing starter not verified.",
            }

        sim = simulate_hitter_matchup_full(
            player_name,
            pitcher_name,
            season,
            batting_order=pregame.get(
                "batting_order"
            ),
            simulations=simulations,
            seed=seed,
        )

        result = simulated_prop_result(
            sim["results"],
            stat_key,
            line,
        )

        recommendation = result[
            "recommendation"
        ]

        probability = result[
            "direction_probability"
        ]

        if recommendation == "PASS":
            confidence = "PASS"
        elif probability >= 0.67:
            confidence = "HIGH"
        else:
            confidence = "MODERATE"

        return {
            "available": True,
            "model_version": sim[
                "model_version"
            ],
            "player": player_name,
            "player_type": player_type,
            "model_prop": model_prop,
            "line": line,
            "projection": result[
                "projection"
            ],
            "p_more": result[
                "p_more"
            ],
            "p_less": result[
                "p_less"
            ],
            "p_push": result[
                "p_push"
            ],
            "model_direction": result[
                "model_direction"
            ],
            "lean": recommendation,
            "qualifies": (
                recommendation
                in ("MORE", "LESS")
            ),
            "confidence": confidence,
            "readiness": readiness,
            "pregame": pregame,
            "opposing_starter": pitcher_name,
            "simulations": simulations,
            "market_used": False,
            "full_team_state_model": sim[
                "run_rbi_context"
            ][
                "full_team_state_model"
            ],
        }

    if player_type == "pitcher":
        stat_key = PITCHER_PROP_MAP.get(
            model_prop
        )

        if not stat_key:
            raise ValueError(
                f"Unsupported V2 pitcher prop: {model_prop}"
            )

        sim = simulate_pitcher_matchup_full(
            player_name,
            season,
            simulations=simulations,
            seed=seed,
        )

        result = simulated_prop_result(
            sim["results"],
            stat_key,
            line,
        )

        recommendation = result[
            "recommendation"
        ]

        probability = result[
            "direction_probability"
        ]

        if recommendation == "PASS":
            confidence = "PASS"
        elif probability >= 0.67:
            confidence = "HIGH"
        else:
            confidence = "MODERATE"

        return {
            "available": True,
            "model_version": sim[
                "model_version"
            ],
            "player": player_name,
            "player_type": player_type,
            "model_prop": model_prop,
            "line": line,
            "projection": result[
                "projection"
            ],
            "p_more": result[
                "p_more"
            ],
            "p_less": result[
                "p_less"
            ],
            "p_push": result[
                "p_push"
            ],
            "model_direction": result[
                "model_direction"
            ],
            "lean": recommendation,
            "qualifies": (
                recommendation
                in ("MORE", "LESS")
            ),
            "confidence": confidence,
            "readiness": "PREGAME_PENDING",
            "pregame": pregame,
            "simulations": simulations,
            "market_used": False,
            "lineup_verified": sim[
                "lineup_verified"
            ],
            "win_model_verified": sim[
                "win_model_verified"
            ],
            "note": (
                "Pitcher V2 remains pending until "
                "confirmed opposing lineup is supplied."
            ),
        }

    raise ValueError(
        f"Unsupported player type: {player_type}"
    )


# ============================================================
# V2 CONFIRMED-LINEUP PITCHER ENGINE
# ============================================================

def _confirmed_opposing_lineup(
    pitcher_name,
    team_id,
    opponent_id,
    season=2026,
):
    """
    Return ONLY an actual MLB confirmed opposing batting order.

    No projected lineups.
    No guessed hitters.
    """

    from mlb_model import (
        _schedule_game_full,
        _live_feed,
        _confirmed_lineups,
    )

    game = _schedule_game_full(
        int(team_id),
        int(opponent_id),
    )

    if not game:
        return {
            "confirmed": False,
            "lineup": [],
            "reason": "No matching MLB game.",
        }

    try:
        feed = _live_feed(
            game["game_pk"]
        )
    except Exception as exc:
        return {
            "confirmed": False,
            "lineup": [],
            "reason": (
                "MLB live feed unavailable: "
                + str(exc)
            ),
        }

    lineups = _confirmed_lineups(
        feed
    )

    pitcher_side = (
        "home"
        if int(team_id)
        == int(game["home_id"])
        else "away"
    )

    opponent_side = (
        "away"
        if pitcher_side == "home"
        else "home"
    )

    lineup = (
        lineups.get(
            opponent_side
        )
        or []
    )

    if not lineup:
        return {
            "confirmed": False,
            "lineup": [],
            "reason": (
                "Opposing batting order "
                "not confirmed."
            ),
        }

    cleaned = [
        {
            "order": row.get("order"),
            "id": row.get("id"),
            "name": row.get("name"),
            "position": row.get("position"),
        }
        for row in lineup
        if row.get("name")
    ]

    if not cleaned:
        return {
            "confirmed": False,
            "lineup": [],
            "reason": (
                "Confirmed lineup contained "
                "no usable hitters."
            ),
        }

    return {
        "confirmed": True,
        "lineup": cleaned,
        "game_pk": game.get(
            "game_pk"
        ),
        "reason": None,
    }


def build_pitcher_lineup_contexts_v2(
    pitcher_name,
    team_id,
    opponent_id,
    season=2026,
):
    """
    Build one hitter-vs-pitcher V2 context for every
    hitter in the confirmed opposing MLB batting order.
    """

    from mlb_matchup_engine import (
        matchup_context_v2,
    )

    lineup_info = (
        _confirmed_opposing_lineup(
            pitcher_name,
            team_id,
            opponent_id,
            season=season,
        )
    )

    if not lineup_info[
        "confirmed"
    ]:
        return {
            "confirmed": False,
            "lineup": [],
            "contexts": [],
            "errors": [],
            "reason": lineup_info.get(
                "reason"
            ),
        }

    contexts = []
    errors = []

    for hitter in lineup_info[
        "lineup"
    ]:
        name = hitter.get(
            "name"
        )

        order = hitter.get(
            "order"
        )

        try:
            context = matchup_context_v2(
                name,
                pitcher_name,
                season,
                batting_order=order,
            )

            if not context.get(
                "available"
            ):
                errors.append({
                    "player": name,
                    "order": order,
                    "error": (
                        "V2 context unavailable"
                    ),
                })
                continue

            contexts.append({
                "player": name,
                "order": order,
                "context": context,
            })

        except Exception as exc:
            errors.append({
                "player": name,
                "order": order,
                "error": str(exc),
            })

    # Do not call a partial lineup VERIFIED.
    complete = (
        len(contexts)
        == len(
            lineup_info["lineup"]
        )
        and len(contexts) >= 9
    )

    return {
        "confirmed": complete,
        "mlb_lineup_confirmed":
            True,
        "lineup":
            lineup_info[
                "lineup"
            ],
        "contexts":
            contexts,
        "errors":
            errors,
        "reason": (
            None
            if complete
            else (
                "MLB lineup exists but not "
                "all hitter V2 contexts "
                "were available."
            )
        ),
    }


def analyze_v2_pitcher_with_confirmed_lineup(
    pitcher_name,
    model_prop,
    line,
    team_id,
    opponent_id,
    opponent_name=None,
    season=2026,
    simulations=1000,
    seed=20260924,
    win_probability=None,
):
    """
    Pitcher V2:

    confirmed opposing batting order
        ->
    each hitter x pitcher matchup
        ->
    simulated pitcher distribution
        ->
    actual PrizePicks line

    Win probability is deliberately optional.
    """

    from mlb_simulator_v2 import (
        simulate_pitcher_matchup_full,
        simulated_prop_result,
    )

    model_prop = _clean_prop(
        model_prop
    )

    stat_key = PITCHER_PROP_MAP.get(
        model_prop
    )

    if not stat_key:
        raise ValueError(
            "Unsupported V2 pitcher prop: "
            + model_prop
        )

    lineup_data = (
        build_pitcher_lineup_contexts_v2(
            pitcher_name,
            team_id,
            opponent_id,
            season=season,
        )
    )

    raw_contexts = [
        row["context"]
        for row in lineup_data[
            "contexts"
        ]
    ]

    sim = simulate_pitcher_matchup_full(
        pitcher_name,
        season,
        simulations=simulations,
        seed=seed,
        lineup_contexts=(
            raw_contexts
            if lineup_data[
                "confirmed"
            ]
            else None
        ),
        win_probability=
            win_probability,
    )

    result = simulated_prop_result(
        sim["results"],
        stat_key,
        float(line),
    )

    recommendation = result[
        "recommendation"
    ]

    probability = result[
        "direction_probability"
    ]

    # Baseball props other than PFS can become
    # context-ready once the full lineup is built.
    #
    # PFS stays pending when the win component has
    # not been modeled defensibly.
    if not lineup_data[
        "confirmed"
    ]:
        readiness = (
            "PREGAME_PENDING"
        )

    elif (
        model_prop
        == "pitcher_fantasy_score"
        and win_probability is None
    ):
        readiness = (
            "PREGAME_PENDING_WIN"
        )

    else:
        readiness = (
            "BASEBALL_CONTEXT_READY"
        )

    if recommendation == "PASS":
        confidence = "PASS"

    elif probability >= 0.67:
        confidence = "HIGH"

    else:
        confidence = "MODERATE"

    # A model can have a direction while still being
    # pending. Do not pretend pending = analytical loss.
    qualifies = (
        recommendation
        in ("MORE", "LESS")
        and readiness
        == "BASEBALL_CONTEXT_READY"
    )

    return {
        "available": True,
        "model_version":
            sim["model_version"],
        "player":
            pitcher_name,
        "player_type":
            "pitcher",
        "model_prop":
            model_prop,
        "line":
            float(line),
        "projection":
            result["projection"],
        "p_more":
            result["p_more"],
        "p_less":
            result["p_less"],
        "p_push":
            result["p_push"],
        "model_direction":
            result[
                "model_direction"
            ],
        "lean":
            recommendation,
        "qualifies":
            qualifies,
        "confidence":
            confidence,
        "readiness":
            readiness,
        "opponent":
            opponent_name,
        "lineup_verified":
            lineup_data[
                "confirmed"
            ],
        "lineup":
            lineup_data[
                "lineup"
            ],
        "lineup_context_count":
            len(
                lineup_data[
                    "contexts"
                ]
            ),
        "lineup_errors":
            lineup_data[
                "errors"
            ],
        "win_model_verified":
            (
                win_probability
                is not None
            ),
        "simulations":
            simulations,
        "market_used":
            False,
    }


# ============================================================
# CONFIRMED LINEUP TEAM-STATE HITTER ADAPTER
# ============================================================

def build_hitter_team_contexts_v2(
    hitter_name,
    opposing_pitcher,
    team_id,
    opponent_id,
    season=2026,
):
    """
    Build all 9 hitter contexts for the selected hitter's
    confirmed team batting order.

    We reuse the confirmed-lineup helper by treating the
    opposing pitcher as the pitcher and the hitter's club
    as that pitcher's opponent.
    """

    from mlb_matchup_engine import (
        matchup_context_v2,
    )

    lineup_info = (
        _confirmed_opposing_lineup(
            opposing_pitcher,
            opponent_id,
            team_id,
            season=season,
        )
    )

    if not lineup_info[
        "confirmed"
    ]:
        return {
            "confirmed": False,
            "lineup": [],
            "contexts": [],
            "target_index": None,
            "errors": [],
            "reason":
                lineup_info.get(
                    "reason"
                ),
        }

    contexts = []
    errors = []
    target_index = None

    target_norm = (
        str(hitter_name)
        .strip()
        .lower()
    )

    for hitter in lineup_info[
        "lineup"
    ]:

        name = hitter.get(
            "name"
        )

        order = hitter.get(
            "order"
        )

        try:

            context = matchup_context_v2(
                name,
                opposing_pitcher,
                season,
                batting_order=order,
            )

            if not context.get(
                "available"
            ):
                errors.append({
                    "player": name,
                    "order": order,
                    "error":
                        "V2 context unavailable",
                })
                continue

            current_index = len(
                contexts
            )

            contexts.append({
                "player": name,
                "order": order,
                "context": context,
            })

            if (
                str(name)
                .strip()
                .lower()
                == target_norm
            ):
                target_index = (
                    current_index
                )

        except Exception as exc:

            errors.append({
                "player": name,
                "order": order,
                "error": str(exc),
            })

    complete = (
        len(contexts) == 9
        and target_index is not None
        and not errors
    )

    return {
        "confirmed":
            complete,

        "lineup":
            lineup_info[
                "lineup"
            ],

        "contexts":
            contexts,

        "target_index":
            target_index,

        "errors":
            errors,

        "reason":
            (
                None
                if complete
                else (
                    "Confirmed lineup could not "
                    "produce all 9 V2 contexts."
                )
            ),
    }


def analyze_v2_hitter_team_state(
    player_name,
    model_prop,
    line,
    team_id,
    opponent_id,
    opponent_name=None,
    season=2026,
    simulations=1000,
    seed=20260924,
):
    """
    Full confirmed-lineup hitter simulation.

    PrizePicks line is applied AFTER baseball simulation.
    Market is not used.
    """

    from mlb_model import (
        verified_pregame_context,
    )

    from mlb_simulator_v2 import (
        simulate_confirmed_lineup_hitter_v2,
        simulated_prop_result,
    )

    model_prop = _clean_prop(
        model_prop
    )

    stat_key = HITTER_PROP_MAP.get(
        model_prop
    )

    if not stat_key:
        raise ValueError(
            "Unsupported hitter prop: "
            + model_prop
        )

    pregame = verified_pregame_context(
        player_name,
        "hitter",
        int(team_id),
        int(opponent_id),
        season=season,
    )

    if (
        pregame.get("lineup")
        == "confirmed"
        and pregame.get(
            "in_starting_lineup"
        ) is False
    ):
        return {
            "available": True,
            "player": player_name,
            "model_prop": model_prop,
            "line": float(line),
            "lean": "PASS",
            "qualifies": False,
            "readiness":
                "PASS_NOT_IN_LINEUP",
            "market_used": False,
        }

    pitcher = pregame.get(
        "starter_name"
    )

    if not pitcher:
        return {
            "available": False,
            "player": player_name,
            "model_prop": model_prop,
            "line": float(line),
            "lean": "PASS",
            "qualifies": False,
            "readiness":
                "PREGAME_PENDING",
            "reason":
                "Opposing starter not verified.",
            "market_used": False,
        }

    team = build_hitter_team_contexts_v2(
        player_name,
        pitcher,
        team_id,
        opponent_id,
        season=season,
    )

    if not team[
        "confirmed"
    ]:
        return {
            "available": False,
            "player": player_name,
            "model_prop": model_prop,
            "line": float(line),
            "lean": "PASS",
            "qualifies": False,
            "readiness":
                "PREGAME_PENDING",
            "opposing_starter":
                pitcher,
            "lineup":
                team["lineup"],
            "lineup_errors":
                team["errors"],
            "reason":
                team["reason"],
            "market_used": False,
        }

    raw_contexts = [
        row["context"]
        for row in team[
            "contexts"
        ]
    ]

    sim = (
        simulate_confirmed_lineup_hitter_v2(
            raw_contexts,
            team[
                "target_index"
            ],
            simulations=
                simulations,
            seed=seed,
        )
    )

    result = simulated_prop_result(
        sim["results"],
        stat_key,
        float(line),
    )

    probability = result[
        "direction_probability"
    ]

    recommendation = result[
        "recommendation"
    ]

    if recommendation == "PASS":
        confidence = "PASS"

    elif probability >= 0.67:
        confidence = "HIGH"

    else:
        confidence = "MODERATE"

    return {
        "available": True,
        "model_version":
            sim["model_version"],
        "player":
            player_name,
        "player_type":
            "hitter",
        "model_prop":
            model_prop,
        "line":
            float(line),
        "opponent":
            opponent_name,
        "opposing_starter":
            pitcher,
        "projection":
            result[
                "projection"
            ],
        "p_more":
            result["p_more"],
        "p_less":
            result["p_less"],
        "p_push":
            result["p_push"],
        "model_direction":
            result[
                "model_direction"
            ],
        "lean":
            recommendation,
        "qualifies":
            (
                recommendation
                in ("MORE", "LESS")
            ),
        "confidence":
            confidence,
        "readiness":
            "BASEBALL_CONTEXT_READY",
        "lineup_verified":
            True,
        "lineup_context_count":
            len(raw_contexts),
        "batting_order":
            pregame.get(
                "batting_order"
            ),
        "average_team_runs":
            sim[
                "average_team_runs"
            ],
        "full_team_state_model":
            True,
        "simulations":
            simulations,
        "market_used":
            False,
    }


# ============================================================
# MLB V2 INDEPENDENT MARKET DIAGNOSTIC
# ============================================================

def attach_v2_market_diagnostic(
    baseball_result,
    event_id,
    player_name,
    model_prop,
    pp_line,
    force_refresh=False,
):
    """
    Attach independent PropLine market information AFTER
    the MLB V2 baseball model has finished.

    CRITICAL V2 RULE:

    Market data may NOT modify:
      projection
      P(MORE)
      P(LESS)
      P(PUSH)
      model direction
      baseball recommendation
      qualifies
      confidence

    The market is diagnostic metadata only.
    """

    from propline_market import (
        get_mlb_market_consensus,
    )

    result = dict(
        baseball_result
    )

    protected = {
        "projection":
            result.get("projection"),

        "p_more":
            result.get("p_more"),

        "p_less":
            result.get("p_less"),

        "p_push":
            result.get("p_push"),

        "model_direction":
            result.get(
                "model_direction"
            ),

        "lean":
            result.get("lean"),

        "qualifies":
            result.get(
                "qualifies"
            ),

        "confidence":
            result.get(
                "confidence"
            ),
    }

    result[
        "market_used"
    ] = False

    result[
        "market_diagnostic_checked"
    ] = False

    result[
        "market_diagnostic"
    ] = "MARKET_UNAVAILABLE"

    result[
        "market_agreement"
    ] = None

    result[
        "independent_market_available"
    ] = False

    result[
        "independent_market_lean"
    ] = None

    result[
        "independent_market_probability"
    ] = None

    result[
        "independent_market_strength"
    ] = "UNAVAILABLE"

    result[
        "independent_market_books"
    ] = 0

    result[
        "independent_market_dispersion"
    ] = None

    result[
        "independent_market_reason"
    ] = None

    if not event_id:

        result[
            "independent_market_reason"
        ] = "EVENT_ID_MISSING"

        return result

    try:

        market = (
            get_mlb_market_consensus(
                event_id=event_id,
                player_name=player_name,
                model_prop=model_prop,
                pp_line=float(pp_line),
                force_refresh=
                    force_refresh,
            )
        )

    except Exception as exc:

        result[
            "independent_market_reason"
        ] = (
            "MARKET_REQUEST_FAILED: "
            + str(exc)
        )

        return result

    available = bool(
        market.get(
            "available"
        )
    )

    result[
        "market_diagnostic_checked"
    ] = True

    result[
        "independent_market_available"
    ] = available

    result[
        "independent_market_reason"
    ] = market.get(
        "reason"
    )

    result[
        "independent_market_lean"
    ] = market.get(
        "market_lean"
    )

    result[
        "independent_market_probability"
    ] = market.get(
        "market_probability"
    )

    result[
        "independent_market_strength"
    ] = market.get(
        "market_strength",
        "UNAVAILABLE",
    )

    result[
        "independent_market_books"
    ] = (
        market.get(
            "books_at_exact_line"
        )
        or market.get(
            "market_books"
        )
        or 0
    )

    result[
        "independent_market_dispersion"
    ] = market.get(
        "market_dispersion"
    )

    result[
        "independent_market_outliers_removed"
    ] = (
        market.get(
            "outliers_removed"
        )
        or market.get(
            "market_outliers_removed"
        )
        or 0
    )

    if not available:

        result[
            "market_diagnostic"
        ] = "MARKET_UNAVAILABLE"

        return result

    market_lean = str(
        market.get(
            "market_lean"
        )
        or "NEUTRAL"
    ).upper()

    market_strength = str(
        market.get(
            "market_strength"
        )
        or "INSUFFICIENT"
    ).upper()

    model_direction = str(
        protected[
            "model_direction"
        ]
        or "PASS"
    ).upper()

    if (
        market_strength
        == "INSUFFICIENT"
    ):

        diagnostic = (
            "INSUFFICIENT_MARKET_DATA"
        )

        agreement = None

    elif market_lean == "NEUTRAL":

        diagnostic = (
            "MARKET_NEUTRAL"
        )

        agreement = None

    elif model_direction not in (
        "MORE",
        "LESS",
    ):

        diagnostic = (
            "MODEL_DIRECTION_UNAVAILABLE"
        )

        agreement = None

    elif (
        model_direction
        == market_lean
    ):

        diagnostic = (
            "MODEL_MARKET_AGREE"
        )

        agreement = True

    else:

        diagnostic = (
            "MARKET_DISAGREEMENT_RISK_FLAG"
        )

        agreement = False

    result[
        "market_diagnostic"
    ] = diagnostic

    result[
        "market_agreement"
    ] = agreement

    # --------------------------------------------------------
    # ASSERT MARKET DID NOT MODIFY BASEBALL MODEL
    # --------------------------------------------------------

    for key, value in (
        protected.items()
    ):

        if result.get(key) != value:

            raise AssertionError(
                "V2 market diagnostic "
                "modified baseball field: "
                + key
            )

    # market_used remains False because the market was
    # observed, not used to create/alter the prediction.
    result[
        "market_used"
    ] = False

    return result


# ============================================================
# MLB V2 GAME -> PROPLINE MARKET DIAGNOSTIC
# ============================================================

def attach_v2_market_for_game(
    baseball_result,
    away_team,
    home_team,
    start_time,
    player_name,
    model_prop,
    pp_line,
    force_refresh=False,
):
    """
    Resolve the PropLine event from the MLB game, then attach
    independent exact-line market information AFTER V2.

    MARKET IS DIAGNOSTIC ONLY.

    It may not modify:
      projection
      p_more
      p_less
      p_push
      model_direction
      lean
      qualifies
      confidence
    """

    from propline_market import (
        get_mlb_market_for_game,
    )

    result = dict(baseball_result)

    protected_keys = (
        "projection",
        "p_more",
        "p_less",
        "p_push",
        "model_direction",
        "lean",
        "qualifies",
        "confidence",
    )

    protected = {
        key: result.get(key)
        for key in protected_keys
    }

    result["market_used"] = False
    result["market_diagnostic_checked"] = False
    result["market_diagnostic"] = "MARKET_UNAVAILABLE"
    result["market_agreement"] = None
    result["independent_market_available"] = False
    result["independent_market_reason"] = None
    result["independent_market_lean"] = None
    result["independent_market_probability"] = None
    result["independent_market_strength"] = "UNAVAILABLE"
    result["independent_market_books"] = 0
    result["independent_market_dispersion"] = None
    result["independent_market_outliers_removed"] = 0
    result["propline_event_id"] = None
    result["propline_event_match_method"] = None

    try:
        market = get_mlb_market_for_game(
            away_team=away_team,
            home_team=home_team,
            start_time=start_time,
            player_name=player_name,
            model_prop=model_prop,
            pp_line=float(pp_line),
            force_refresh=force_refresh,
        )
    except Exception as exc:
        result["independent_market_reason"] = (
            "MARKET_REQUEST_FAILED: " + str(exc)
        )
        return result

    result["market_diagnostic_checked"] = True

    event_match = (
        market.get("event_match")
        or {}
    )

    result["propline_event_id"] = (
        market.get("event_id")
        or event_match.get("event_id")
    )

    result["propline_event_match_method"] = (
        event_match.get("match_method")
    )

    available = bool(
        market.get("available")
    )

    result["independent_market_available"] = available

    result["independent_market_reason"] = (
        market.get("reason")
    )

    result["independent_market_lean"] = (
        market.get("market_lean")
    )

    result["independent_market_probability"] = (
        market.get("market_probability")
    )

    result["independent_market_strength"] = (
        market.get(
            "market_strength",
            "UNAVAILABLE",
        )
    )

    result["independent_market_books"] = (
        market.get("books_at_exact_line")
        or market.get("market_books")
        or 0
    )

    result["independent_market_dispersion"] = (
        market.get("market_dispersion")
    )

    result["independent_market_outliers_removed"] = (
        market.get("outliers_removed")
        or market.get(
            "market_outliers_removed"
        )
        or 0
    )

    if not available:
        result["market_diagnostic"] = (
            "MARKET_UNAVAILABLE"
        )

    else:
        market_lean = str(
            market.get("market_lean")
            or "NEUTRAL"
        ).upper()

        market_strength = str(
            market.get("market_strength")
            or "INSUFFICIENT"
        ).upper()

        model_direction = str(
            protected.get("model_direction")
            or "PASS"
        ).upper()

        if market_strength == "INSUFFICIENT":
            result["market_diagnostic"] = (
                "INSUFFICIENT_MARKET_DATA"
            )

        elif market_lean == "NEUTRAL":
            result["market_diagnostic"] = (
                "MARKET_NEUTRAL"
            )

        elif model_direction not in (
            "MORE",
            "LESS",
        ):
            result["market_diagnostic"] = (
                "MODEL_DIRECTION_UNAVAILABLE"
            )

        elif market_lean == model_direction:
            result["market_diagnostic"] = (
                "MODEL_MARKET_AGREE"
            )
            result["market_agreement"] = True

        else:
            result["market_diagnostic"] = (
                "MARKET_DISAGREEMENT_RISK_FLAG"
            )
            result["market_agreement"] = False

    for key, value in protected.items():
        if result.get(key) != value:
            raise AssertionError(
                "MARKET MODIFIED MLB V2 FIELD: "
                + key
            )

    result["market_used"] = False

    return result
