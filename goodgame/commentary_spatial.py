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
    if "six-yard" in lower or "6-yard" in lower or "very close range" in lower:
        distance = 6.5
    elif any(p in lower for p in ("outside the box", "outside the penalty area",
                                 "edge of the box", "outside penalty area")):
        distance = 25.0
    elif any(p in lower for p in ("penalty area", "inside the box", "inside the area",
                                 "center of the box", "centre of the box")):
        distance = 15.0
    elif "midfield" in lower or "halfway line" in lower:
        distance = 50.0
    elif any(p in lower for p in ("wing", "flank", "byline")):
        distance = 26.0
    else:
        return None

    left = bool(re.search(r"\bleft (?:side|wing|flank|byline)\b", lower))
    right = bool(re.search(r"\bright (?:side|wing|flank|byline)\b", lower))
    # Lateral side is from attacking player's view; mirror at the other end.
    y = (34.0 if target > 50 else 66.0) if left else (
        (66.0 if target > 50 else 34.0) if right else 50.0
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
    distances = sorted(
        (math.hypot(sample["x"] - point["x"], sample["y"] - point["y"]), sample)
        for sample in samples
    )
    distance, nearest = distances[0]
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
            shot_zone = _zone(narrative, target)
            if shooter and (shot_zone or spatial.get("shot_actor_anchor")):
                shooter_at = place(shooter, "shooter",
                                   shot_zone or spatial.get("shot_actor_anchor"),
                                   evidence="commentary_zone" if shot_zone else "existing_reconstruction")
                spatial["shot_actor_anchor"] = shooter_at

            assister = next((p for p in players if event.get("related_player_id") is not None
                             and str(p.get("player_id")) == str(event["related_player_id"])), None)
            if assister:
                cross_zone = None
                if "cross from the left" in narrative.casefold():
                    cross_zone = _zone("left wing", target)
                elif "cross from the right" in narrative.casefold():
                    cross_zone = _zone("right wing", target)
                assist_point = (cross_zone or spatial.get("assist_actor_anchor")
                                or _point(target - direction * 34, 42))
                spatial["assist_actor_anchor"] = place(
                    assister, "assister", assist_point,
                    evidence="commentary_zone" if cross_zone else "inferred_assist_area",
                )

            defender = next((p for p in players if spatial.get("outcome_actor_id") is not None
                             and str(p.get("player_id")) == str(spatial["outcome_actor_id"])), None)
            if defender:
                contact = spatial.get("outcome_actor_anchor")
                if contact:
                    place(defender, "goalkeeper" if spatial.get("outcome_kind") == "save"
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
                place(taker, "corner_taker", start, evidence=wing_evidence)
            track = [start, receiver_at]
            spatial.update({
                "source": "commentary_coordinate_supported" if tracking_count else "commentary_inferred",
                "anchor": start,
                "ball_track": track,
                "ball_path": {"start": start, "end": receiver_at},
                "shot_start_index": 0,
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
