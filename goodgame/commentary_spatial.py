"""Commentary-led event geometry and actor placements.

Narrative identifies WHAT happened and WHO/WHERE in broad pitch zones.
Provider ball coordinates provide optional temporal corroboration, never
automatically establish player bodies at the first/last ball samples.
All inferred locations are disclosed to the API consumer.
"""
from __future__ import annotations

import math
import re
from typing import Any


SHOT_KINDS = {"shot", "shot_on_target", "shot_off_target",
              "blocked_shot", "goal", "woodwork", "penalty"}


def _clock(row: dict[str, Any]) -> int:
    try:
        return int(row.get("minute") or 0) - 1 + int(row.get("extra_minute") or 0)
    except (TypeError, ValueError):
        return 0


def _ordered(row: dict[str, Any]) -> tuple[int, int, int]:
    return (_clock(row), int(row.get("sort_order") or 999999), int(row.get("id") or 0))


def _point(x: float, y: float) -> dict[str, float]:
    return {"x": round(max(1.5, min(98.5, x)), 3),
            "y": round(max(1.5, min(98.5, y)), 3)}


def _player_mentions(text: str, players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lower = text.casefold()
    hits = []
    for player in players:
        name = str(player.get("name") or "").strip()
        if name and re.search(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", lower):
            hits.append(player)
    return hits


def _zone(text: str, target: float, *, default_distance: float = 20.0
          ) -> dict[str, float] | None:
    """Attacker-oriented zones from COMMENTARY, never from a ball endpoint."""
    lower = text.casefold()
    # Pitch X is normalized to 0..100 across 105 metres. The penalty area
    # is the OUTER 16.5m-deep box; the smaller box is the 5.5m goal area.
    # Commentary describing close-range headers must stay inside the box,
    # never use a lineup/midfield position just because no coordinate exists.
    six_yard_zone = any(p in lower for p in (
        "six-yard", "6-yard", "six yard", "goal area",
    ))
    if six_yard_zone:
        distance = 4.0  # Inside the 5.5m-deep SMALL goal area
    elif any(p in lower for p in (
        "close-range", "close range", "very close range", "point-blank",
    )):
        distance = 7.5  # Close-range, inside the LARGE penalty area
    elif any(p in lower for p in (
        "outside the box", "outside the penalty area",
        "outside penalty area", "outside the area",
    )):
        distance = 24.0
    elif any(p in lower for p in ("edge of the box", "edge of the penalty area")):
        distance = 16.4  # Outside the large penalty area line
    elif any(p in lower for p in (
        "penalty area", "inside the box", "inside the area",
        "center of the box", "centre of the box",
    )):
        distance = 12.0  # Inside the large 16.5m penalty area
    elif "midfield" in lower or "halfway line" in lower:
        distance = 50.0
    elif any(p in lower for p in ("wing", "flank", "byline")):
        distance = 26.0
    else:
        return None

    left = bool(re.search(r"\bleft (?:side|wing|flank|byline)\b", lower))
    right = bool(re.search(r"\bright (?:side|wing|flank|byline)\b", lower))
    # Lateral side is from attacking player's view; mirror at the other end.
    lateral_offset = 6.0 if six_yard_zone else 16.0
    y = (50.0 - lateral_offset if target > 50 else 50.0 + lateral_offset) if left else (
        (50.0 + lateral_offset if target > 50 else 50.0 - lateral_offset)
        if right else 50.0
    )
    return _point(target - (1 if target > 50 else -1) * distance, y)


def _actor(
    player: dict[str, Any], role: str, at: dict[str, float],
    source: str,
) -> dict[str, Any]:
    return {
        "player_id": player.get("player_id"),
        "name": str(player.get("name") or ""),
        "role": role,
        "team": player.get("team_location"),
        "x": at["x"], "y": at["y"],
        "position_source": source,
    }


def _support_samples(
    game: dict[str, Any], event: dict[str, Any],
) -> list[dict[str, float]]:
    rows = []
    for row in game.get("ball_coordinates") or []:
        try:
            xy = {"x": float(row["x"]), "y": float(row["y"])}
            clock_m, clock_s = str(row["timer"]).split(":", 1)
            seconds = int(clock_m) * 60 + int(clock_s)
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
        if not all(math.isfinite(v) for v in xy.values()):
            continue
        rows.append({**xy, "_second": seconds, "_period": row.get("period_id")})
    if not rows:
        return []
    fractional = all(-0.05 <= row[a] <= 1.05 for row in rows for a in ("x", "y"))
    scale = 100 if fractional else 1
    # Provider samples every several seconds; an event's minute is ordinal.
    # Keep a narrow temporal window and matching period when available.
    second = max(0, _clock(event) * 60)
    relevant = [
        row for row in rows
        if second - 20 <= row["_second"] <= second + 64
        and (event.get("period_id") is None or row["_period"] is None
             or str(event["period_id"]) == str(row["_period"]))
    ]
    return [_point(row["x"] * scale, row["y"] * scale) for row in relevant]


def _nearby(
    point: dict[str, float], samples: list[dict[str, float]],
    radius: float = 10.0,
) -> tuple[dict[str, float], bool]:
    if not samples:
        return point, False
    distance, nearest = min(
        (
            math.hypot(sample["x"] - point["x"], sample["y"] - point["y"]),
            index, sample,
        )
        for index, sample in enumerate(samples)
    )[0::2]
    if distance > radius:
        return point, False
    # Commentary placement leads; tracking is only a small refinement.
    return _point(point["x"] * .85 + nearest["x"] * .15,
                  point["y"] * .85 + nearest["y"] * .15), True


def _match_player(
    text: str, players: list[dict[str, Any]], pattern: str,
) -> dict[str, Any] | None:
    regex = re.search(pattern, text, flags=re.IGNORECASE)
    if not regex:
        return None
    trailing = text[regex.end():].casefold()
    matches = [
        player for player in players
        if re.match(r"\s*" + re.escape(str(player["name"]).strip().casefold()) + r"\b",
                    trailing)
    ]
    return matches[0] if len(matches) == 1 else None


def enrich_replays(
    game: dict[str, Any], events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    players = [p for p in game.get("players") or [] if isinstance(p, dict)]
    comments = [
        row for row in game.get("commentary") or []
        if isinstance(row, dict) and row.get("comment")
    ]
    comments.sort(key=_ordered)
    by_id = {str(row.get("id")): row for row in comments}
    teams = (game.get("home_team") or {}, game.get("away_team") or {})

    for event in events:
        spatial = dict(event.get("spatial") or {})
        kind = str(spatial.get("kind") or "")
        if spatial.get("source") == "decision_only":
            continue

        comment = by_id.get(str(event.get("commentary_id")))
        if comment is None:
            continue
        narrative = str(comment["comment"])
        side = ("home" if str(event.get("team_id")) == str(teams[0].get("id"))
                else "away" if str(event.get("team_id")) == str(teams[1].get("id"))
                else None)
        if side is None:
            continue
        minute = int(event.get("minute") or 0)
        # Home attacks right in 1H; ends swap after halftime.
        attacks_right = (side == "home") == (minute <= 45 or 90 < minute <= 105)
        target = 100.0 if attacks_right else 0.0
        direction = 1.0 if attacks_right else -1.0
        samples = _support_samples(game, event)
        mentions = _player_mentions(narrative, players)
        actors: list[dict[str, Any]] = []
        detail = dict(event.get("detail") or {})
        story = list(detail.get("event_sequence") or [])
        tracking_count = 0

        if kind == "foul":
            # Fouls do not represent a ball traversal. A player can only be
            # shown at an actual time-matched ball sample, never a guessed
            # formation position or a random point on a synthetic path.
            # The provider does not identify who possessed the ball at each
            # timestamp, so this placement is contextual, not measured player
            # tracking. Choose the fouled player when commentary says who won
            # the free kick; otherwise use a single named participant.
            first_sample = samples[0] if samples else None
            event_clock = max(0, _clock(event) * 60)
            explicit_samples = [
                row for row in (game.get("ball_coordinates") or [])
                if isinstance(row, dict)
                and isinstance(row.get("timer"), str)
                and re.fullmatch(r"\d{1,3}:\d{2}", row["timer"])
                and event_clock <= (
                    int(row["timer"].split(":")[0]) * 60
                    + int(row["timer"].split(":")[1])
                ) < event_clock + 60
                and (
                    event.get("period_id") is None
                    or row.get("period_id") is None
                    or str(row["period_id"]) == str(event["period_id"])
                )
            ]
            if not explicit_samples:
                first_sample = None
            elif first_sample is not None:
                # Use earliest sample in this actual minute (instead of the
                # 20-second support period preceding it).
                minute_points = _support_samples(
                    {**game, "ball_coordinates": explicit_samples}, event,
                )
                first_sample = minute_points[0] if minute_points else None

            actor = None
            if first_sample:
                text_lower = narrative.casefold()
                if any(word in text_lower for word in ("earned a free kick", "wins a free kick",
                                                        "won a free kick", "draws a foul",
                                                        "fouled by", "is fouled")):
                    actor = next((p for p in mentions
                                  if str(p["name"]).casefold() in text_lower), None)
                elif (match := re.search(r"\bfouls?\b", text_lower)):
                    # Mentions are returned in lineup order, not text order.
                    # In "Trai Hume fouls Mason Mount", the VICTIM is the
                    # player named after the verb, regardless of squad order.
                    following = [
                        p for p in mentions
                        if text_lower.find(str(p["name"]).strip().casefold()) >= match.end()
                    ]
                    if len(following) == 1:
                        actor = following[0]
                elif len(mentions) == 1:
                    actor = mentions[0]
                if actor and actor.get("player_id") is not None:
                    actors.append(_actor(actor, "fouled_player", first_sample,
                                         "minute_ball_sample_context_not_player_tracking"))
            spatial.update({
                "kind": "foul",
                "source": "foul_position_only",
                "anchor": None,
                "ball_path": None,
                "ball_track": [],
                "actor_positions": actors,
                "actor_placement_policy": "commentary_first",
                "coordinate_support_points": len(explicit_samples),
                "reconstruction_note": (
                    "Foul: no ball flight. Player shown only at a time-matched "
                    "ball location; ball coordinates are not measured player positions."
                    if actors else
                    "Foul: no ball flight or player position displayed because "
                    "the provider did not identify a time-matched ball location."
                ),
            })
            event["ball_track"] = []
            event["ball_path"] = None
            event["spatial"] = spatial
            event["detail"] = detail
            continue

        def place(player: dict[str, Any] | None, role: str,
                  anchor: dict[str, float] | None, *, evidence: str) -> dict[str, float] | None:
            nonlocal tracking_count
            if not player or not anchor or player.get("player_id") is None:
                return anchor
            at, supported = _nearby(anchor, samples, 10 if evidence == "commentary_zone" else 6)
            if supported:
                tracking_count += 1
            if not any(str(p["player_id"]) == str(player["player_id"]) for p in actors):
                actors.append(_actor(player, role, at, (
                    "commentary_zone_coordinate_refined" if supported
                    else evidence
                )))
            return at

        if kind in SHOT_KINDS:
            shooter = next((p for p in players if event.get("player_id") is not None
                            and str(p.get("player_id")) == str(event["player_id"])), None)
            # Don't position the SHOOTER at the passer's wing merely because
            # the same commentary later mentions a cross from that flank.
            shooter_clause = re.split(
                r"\b(?:assisted by|with [\w\s'-]+ providing the assist|"
                r"assist(?: came)? from|cross from|crossed by)\b",
                narrative, maxsplit=1, flags=re.IGNORECASE,
            )[0]
            shot_zone = _zone(shooter_clause, target)
            if shooter and (shot_zone or spatial.get("shot_actor_anchor")):
                shooter_at = place(shooter, "shooter",
                                   shot_zone or spatial.get("shot_actor_anchor"),
                                   evidence="commentary_zone" if shot_zone else "existing_reconstruction")
                spatial["shot_actor_anchor"] = shooter_at

            assister = next((p for p in players if event.get("related_player_id") is not None
                             and str(p.get("player_id")) == str(event["related_player_id"])), None)
            if assister:
                cross_zone = None
                cross_source = "inferred_assist_area"
                # If a header follows a documented corner, the next named
                # CROSSER is near the attacking wing/byline, not midfield.
                # Crucially: crossing after a corner is NOT evidence that
                # this player took the original corner.
                if re.search(r"\b(?:following|after|from) (?:a |the )?corner(?: kick)?\b",
                             narrative.casefold()):
                    preceding = [
                        row for row in events
                        if row is not event
                        and str(row.get("team_id")) == str(event.get("team_id"))
                        and str((row.get("spatial") or {}).get("kind")) == "corner"
                        and 0 <= _clock(event) - _clock(row) <= 2
                        and (
                            event.get("period_id") is None or row.get("period_id") is None
                            or str(event["period_id"]) == str(row["period_id"])
                        )
                    ]
                    if len(preceding) == 1:
                        corner_start = (preceding[0].get("spatial") or {}).get("ball_path") or {}
                        point = corner_start.get("start") or {}
                        corner_y = float(point.get("y", 50))
                        if corner_y != 50:
                            cross_zone = _point(
                                target - direction * 12,
                                18.0 if corner_y < 50 else 82.0,
                            )
                            cross_source = "inferred_cross_after_corner"
                if "cross from the left" in narrative.casefold():
                    cross_zone = _zone("left wing", target)
                    cross_source = "commentary_zone"
                elif "cross from the right" in narrative.casefold():
                    cross_zone = _zone("right wing", target)
                    cross_source = "commentary_zone"
                assist_point = (cross_zone or spatial.get("assist_actor_anchor")
                                or _point(target - direction * 34, 42))
                spatial["assist_actor_anchor"] = place(
                    assister, "assister", assist_point,
                    evidence=cross_source if cross_zone else "inferred_assist_area",
                )

            defender = next((p for p in players if spatial.get("outcome_actor_id") is not None
                             and str(p.get("player_id")) == str(spatial["outcome_actor_id"])), None)
            outcome = spatial.get("outcome_kind")
            if defender is None and outcome in {"save", "block"}:
                # A named defensive actor is valid only on the opposing team.
                reported = _match_player(
                    narrative, players,
                    r"\b(?:saved by|save by|blocked by|block by|deflected by)\b",
                )
                if reported and reported.get("team_id") != event.get("team_id"):
                    defender = reported
                    spatial["outcome_actor_id"] = reported.get("player_id")
                    spatial["outcome_actor_name"] = reported.get("name")
                    spatial["outcome_actor_team"] = reported.get("team_location")
                    spatial["outcome_actor_role"] = (
                        "Goalkeeper" if outcome == "save" else "Defender"
                    )
                    spatial["outcome_actor_identification_source"] = "commentary"
            if defender:
                contact = spatial.get("outcome_actor_anchor")
                if contact is None:
                    shot_start = spatial.get("shot_actor_anchor")
                    if shot_start:
                        contact = _point(
                            shot_start["x"] + direction * (
                                12.0 if outcome == "block" else 20.0
                            ),
                            shot_start["y"] * .4 + 50.0 * .6,
                        )
                        spatial["outcome_actor_anchor"] = contact
                        spatial["outcome_actor_anchor_source"] = "inferred_contact_area"
                if contact:
                    place(defender, "goalkeeper" if outcome == "save"
                          else "blocker", contact, evidence="inferred_contact_area")

        if kind == "corner":
            # A corner AWARD and a corner DELIVERY are not synonymous. Look
            # ahead to the first same-team attempt explicitly from a corner.
            # When present it tells us the receiver, crossing player and zone.
            follow = None
            for candidate in comments:
                if _ordered(candidate) <= _ordered(comment):
                    continue
                if _clock(candidate) - _clock(comment) > 2:
                    break
                text = str(candidate["comment"])
                lower = text.casefold()
                if not re.search(r"\b(?:after|from|following) (?:a |the )?corner\b", lower):
                    continue
                found = _player_mentions(text, players)
                if not any(p.get("team_id") == event.get("team_id") for p in found):
                    continue
                follow = candidate
                break

            combined = str(follow["comment"]) if follow else narrative
            receiver = None
            taker = None
            receiver_zone = _zone(combined, target)
            if follow:
                named = [p for p in _player_mentions(combined, players)
                         if str(p.get("team_id")) == str(event.get("team_id"))]
                # A header/shot actor precedes the action description.
                m = re.search(r"\b(?:header|headed|heads|shot|attempt|strike)\b",
                              combined.casefold())
                earlier = [
                    p for p in named
                    if m and combined.casefold().find(str(p["name"]).casefold()) < m.start()
                ]
                if len(earlier) == 1:
                    receiver = earlier[0]
                taker = _match_player(
                    combined, named,
                    r"\b(?:assisted by|assist(?: came)? from|cross from|crossed by)\b",
                )

            # Corner wing is known if commentary states left/right, or
            # coordinate samples actually approach an attacking corner.
            lower = narrative.casefold()
            if re.search(r"\bleft (?:corner|side|wing)\b", lower):
                y = 2.0 if attacks_right else 98.0
                wing_evidence = "commentary_zone"
            elif re.search(r"\bright (?:corner|side|wing)\b", lower):
                y = 98.0 if attacks_right else 2.0
                wing_evidence = "commentary_zone"
            else:
                corner_candidates = [
                    p for p in samples
                    if abs(p["x"] - target) <= 12
                    and (p["y"] <= 15 or p["y"] >= 85)
                ]
                if corner_candidates:
                    near = min(corner_candidates, key=lambda p: abs(p["x"] - target))
                    y = 2.0 if near["y"] < 50 else 98.0
                    wing_evidence = "time_matched_ball_coordinates"
                else:
                    # Preserve original reconstruction's choice, label it
                    # illustrative rather than assert an unreported side.
                    old = (spatial.get("ball_path") or {}).get("start") or {}
                    y = 2.0 if float(old.get("y", 2)) < 50 else 98.0
                    wing_evidence = "illustrative_corner_side"

            start = _point(target - direction * 1.5, y)
            receiver_at = receiver_zone or _point(
                target - direction * 13,
                50.0 if not receiver else (45.0 if y < 50 else 55.0),
            )
            receiver_at, supported = _nearby(receiver_at, samples, 10)
            if supported:
                tracking_count += 1
            if receiver:
                place(receiver, "receiver", receiver_at,
                      evidence="commentary_zone" if receiver_zone else "inferred_box_receiver")
            if taker:
                # "Cross following a corner kick" identifies a crosser, not
                # necessarily the original corner taker.
                took_corner = re.search(
                    r"\b(?:corner (?:kick )?(?:taken|delivered|swung in) by|"
                    r"takes? (?:the|a) corner)\b",
                    combined.casefold(),
                )
                if took_corner:
                    place(taker, "corner_taker", start, evidence=wing_evidence)
                else:
                    crosser = _point(
                        target - direction * 12,
                        18.0 if y < 50 else 82.0,
                    )
                    place(taker, "crosser", crosser,
                          evidence="inferred_cross_after_corner")
            track = [start, receiver_at]
            # If the linked commentary explicitly reports a header/shot and
            # a direction or save, show the actual action sequence:
            # corner delivery -> receiver's contact -> outcome. Otherwise
            # stop at the receiver rather than invent a shot into the net.
            if follow and receiver and re.search(
                r"\b(?:header|heads|headed|shot|attempt)\b", combined.casefold()
            ):
                follow_lower = combined.casefold()
                missed = re.search(
                    r"\b(?:misses|missed|wide)\b.{0,110}\b(?:to (?:the )?|wide to (?:the )?)(left|right)\b",
                    follow_lower,
                )
                if missed:
                    side_factor = -1 if missed.group(1) == "left" else 1
                    lateral = (1 if attacks_right else -1) * side_factor
                    shot_end = _point(target - direction * 0.8, 50 + 9 * lateral)
                elif re.search(r"\b(?:saved|save by|saves)\b", follow_lower):
                    shot_end = _point(target - direction * 2, 50)
                elif re.search(r"\b(?:misses high|over the bar|too high)\b", follow_lower):
                    shot_end = _point(target - direction * 0.8, 50)
                else:
                    shot_end = None
                if shot_end:
                    track.append(shot_end)
                    spatial["shot_start_index"] = 1
                    spatial["phases"] = [
                        {"kind": "corner_delivery", "start_index": 0, "end_index": 1},
                        {"kind": "shot", "start_index": 1, "end_index": 2},
                    ]
            spatial.update({
                "source": "commentary_coordinate_supported" if tracking_count else "commentary_inferred",
                "anchor": start,
                "ball_track": track,
                "ball_path": {"start": start, "end": receiver_at},
                "shot_start_index": spatial.get("shot_start_index", 0),
                "corner_side_source": wing_evidence,
                "reconstruction_note": (
                    "Corner delivery inferred from commentary; player locations are zone estimates, "
                    "not tracked body positions."
                ),
            })
            event["ball_track"] = track
            event["ball_path"] = spatial["ball_path"]

            if follow:
                detail["follow_up_commentary_id"] = follow.get("id")
                phases = [
                    {"kind": "corner", "label": "Corner awarded",
                     "evidence": "provider_commentary"},
                    {"kind": "delivery", "label": "Cross / corner delivery",
                     "actor_name": taker.get("name") if taker else None,
                     "actor_id": taker.get("player_id") if taker else None,
                     "evidence": "linked_commentary"},
                    {"kind": "attempt", "label": "Header / shot from corner",
                     "actor_name": receiver.get("name") if receiver else None,
                     "actor_id": receiver.get("player_id") if receiver else None,
                     "evidence": "linked_commentary"},
                ]
                detail["event_sequence"] = phases
            else:
                detail["event_sequence"] = [
                    {"kind": "corner", "label": "Corner awarded",
                     "evidence": "provider_commentary"},
                    {"kind": "delivery", "label": "Illustrative delivery toward box",
                     "evidence": "inferred_from_corner"},
                ]

        elif kind == "offside":
            # Comments may name passers, receivers, foulers and victims even
            # though no event-specific player_positions were stored.
            # Anchor them to described broad zones, not ball path endpoints.
            zone = _zone(narrative, target)
            if zone is None:
                zone = _point(target - direction * (20 if kind == "offside" else 38), 50)
            involved = _player_mentions(narrative, players)
            for index, player in enumerate(involved[:3]):
                role = "offside_player" if kind == "offside" and index == 0 else (
                    "fouler" if kind == "foul" and index == 0 else "involved"
                )
                # Nearby actors are offset just enough not to overlap. No
                # claim of precise positions without player tracking.
                here = _point(zone["x"] - direction * min(4, index * 3),
                              zone["y"] + min(6, index * 3))
                place(player, role, here,
                      evidence="commentary_zone" if _zone(narrative, target)
                      else "inferred_action_area")

        if actors:
            spatial["actor_positions"] = actors
        if kind in SHOT_KINDS and spatial.get("shot_actor_anchor") and spatial.get("ball_track"):
            # Existing spatial planner already keeps semantic launch and ball
            # nodes distinct; preserve its goal/save/block outcome endpoint.
            # Only update the launch node when it is supported by commentary.
            track = list(spatial["ball_track"])
            idx = max(0, min(len(track)-1, int(spatial.get("shot_start_index") or 0)))
            if any(p["role"] == "shooter" for p in actors):
                track[idx] = {**track[idx], **spatial["shot_actor_anchor"]}
                if idx > 0 and spatial.get("assist_actor_anchor") and any(
                    p["role"] == "assister" for p in actors
                ):
                    track[0] = {**track[0], **spatial["assist_actor_anchor"]}
                spatial["ball_track"] = track
                spatial["ball_path"] = {"start": track[0], "end": track[-1]}
                event["ball_track"] = track
                event["ball_path"] = spatial["ball_path"]

        if actors or kind == "corner":
            spatial["actor_placement_policy"] = "commentary_first"
            spatial["coordinate_support_points"] = len(samples)
            spatial["reconstruction_note"] = (
                spatial.get("reconstruction_note") or
                "Players placed by commentary-described zones; nearby timed ball samples "
                "only refine those estimates."
            )
        event["spatial"] = spatial
        event["detail"] = detail

    return events
