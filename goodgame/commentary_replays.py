"""Commentary-backed spatial replay selection.

Structured events and statistics enrich a replay; they do not independently
authorize one. Preserve game.events/timeline for non-spatial UI consumers.
"""
from __future__ import annotations

import re
from typing import Any, Callable


def _kind(comment: dict[str, Any]) -> str | None:
    text = str(comment.get("comment") or "").casefold()
    if not text.strip():
        return None
    if comment.get("is_goal") is True or re.search(r"\bgoal!|\bscores\b", text):
        return "goal"
    if re.search(r"\b(?:hits?|strikes?) (?:the )?(?:post|bar|crossbar)\b|\bwoodwork\b", text):
        return "woodwork"
    if re.search(r"\b(?:shot|attempt|strike|header)\b.{0,60}\bblock(?:ed|s)?\b|\bblocked\b.{0,45}\b(?:shot|attempt|strike)\b", text):
        return "blocked_shot"
    if re.search(r"\b(?:saved|saves|save by|denied by)\b", text) and re.search(r"\b(?:shot|attempt|strike|header|effort)\b", text):
        return "shot_on_target"
    if re.search(r"\b(?:misses|missed|wide|off target|over the bar)\b", text) and re.search(r"\b(?:shot|attempt|header|heads|effort)\b", text):
        return "shot_off_target"
    if re.search(r"\b(?:shot|attempt|header|heads the ball|shoots|strike)\b", text):
        return "shot"
    if re.search(r"\b(?:corner awarded|wins a corner|win a corner|concedes a corner)\b", text):
        return "corner"
    if re.search(r"\boffside\b", text):
        return "offside"
    if re.search(r"\b(?:yellow card|red card|booked)\b", text):
        return "card"
    if re.search(r"\b(?:foul|free kick)\b", text):
        return "foul"
    return None


def commentary_simulations(
    game: dict[str, Any],
    events: list[dict[str, Any]],
    build_events: Callable[[dict[str, Any]], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Return only actions described by commentary, plus composite VAR stories.

    For explicit unmatched action commentary, create a normalized event and
    let the existing spatial engine apply the SAME geometry and identity rules.
    """
    comments = [
        entry for entry in game.get("commentary", []) or []
        if isinstance(entry, dict) and entry.get("id") is not None
    ]
    if not comments:
        return []

    by_id = {str(entry["id"]): entry for entry in comments}
    attempt_kinds = {
        "goal", "woodwork", "shot", "shot_on_target",
        "shot_off_target", "blocked_shot", "penalty",
    }

    def is_backed(event: dict[str, Any]) -> bool:
        kind = str((event.get("spatial") or {}).get("kind") or event.get("semantic_type") or "")
        detail = event.get("detail") or {}
        if kind in {"penalty_disallowed", "goal_disallowed"}:
            if detail.get("ordered_commentary_steps"):
                return True
        comment = by_id.get(str(event.get("commentary_id")))
        if comment is None:
            return False
        action = _kind(comment)
        if kind in attempt_kinds:
            return action in attempt_kinds
        return action == kind

    selected = [event for event in events if is_backed(event)]
    consumed = {
        str(event["commentary_id"]) for event in selected
        if event.get("commentary_id") is not None
    }
    for event in selected:
        consumed.update(str(identifier) for identifier in (
            (event.get("detail") or {}).get("commentary_step_ids") or []
        ))

    # First prefer structured provider actions enriched with narrative detail.
    # Unmatched commentary still deserves a replay if it names a recognized
    # action and establishes which side performed it.
    names = {
        "goal": "Goal", "woodwork": "Woodwork", "shot": "Shot",
        "shot_on_target": "Shot On Target",
        "shot_off_target": "Shot Off Target",
        "blocked_shot": "Blocked Shot", "corner": "Corner",
        "offside": "Offside", "card": "Card", "foul": "Foul",
    }
    players = [
        player for player in game.get("players", []) or []
        if isinstance(player, dict) and player.get("name")
    ]
    teams = [game.get("home_team") or {}, game.get("away_team") or {}]
    added: list[dict[str, Any]] = []
    comments.sort(key=lambda entry: (
        entry.get("minute") if entry.get("minute") is not None else 999,
        entry.get("extra_minute") if entry.get("extra_minute") is not None else 0,
        entry.get("sort_order") if entry.get("sort_order") is not None else 999999,
    ))
    for index, comment in enumerate(comments):
        identifier = comment["id"]
        if str(identifier) in consumed or comment.get("minute") is None:
            continue
        action = _kind(comment)
        if action not in names:
            continue
        text = str(comment.get("comment") or "")
        lower = text.casefold()
        mentions = [
            player for player in players
            if str(player["name"]).strip().casefold() in lower
        ]
        actor = None
        if action in attempt_kinds and mentions:
            # A shot's actor normally appears before the action verb; the
            # subsequent name can be a keeper/defender or the assister.
            action_pos = re.search(r"\b(?:shot|attempt|strike|header|shoots)\b", lower)
            before = [
                player for player in mentions
                if action_pos and lower.find(str(player["name"]).strip().casefold()) < action_pos.start()
            ]
            if len(before) == 1:
                actor = before[0]
        if actor is None and len(mentions) == 1:
            actor = mentions[0]
        team_id = actor.get("team_id") if actor else None
        mentioned_teams = [
            team for team in teams
            if team.get("name") and str(team["name"]).casefold() in lower
        ]
        if action == "corner":
            # In "Corner awarded to Home after Defender concedes", the named
            # defender belongs to Away. Awarding team overrides his identity.
            award = [
                team for team in mentioned_teams
                if (
                    "corner awarded to " + str(team["name"]).casefold() in lower
                    or str(team["name"]).casefold() + " wins a corner" in lower
                    or str(team["name"]).casefold() + " win a corner" in lower
                    or str(team["name"]).casefold() + " awarded a corner" in lower
                )
            ]
            if len(award) == 1:
                team_id = award[0].get("id")
                actor = None  # A conceding defender is not the corner taker.
            elif len(mentioned_teams) == 1:
                team_id = mentioned_teams[0].get("id")
                actor = None
            else:
                # Without reliable beneficiary data, don't infer the corner
                # taker's team from an opposing defender's mention.
                team_id = None
                actor = None
        elif team_id is None and len(mentioned_teams) == 1:
            team_id = mentioned_teams[0].get("id")
        if team_id is None:
            continue
        try:
            row_id = -1000000000 - int(identifier)
        except (ValueError, TypeError):
            row_id = -1000000000 - index
        added.append({
            "id": row_id,
            "source_commentary_id": identifier,
            "minute": comment["minute"],
            "extra_minute": comment.get("extra_minute"),
            "sort_order": comment.get("sort_order"),
            "type": names[action],
            "text": names[action],
            "team_id": team_id,
            "player_id": actor.get("player_id") if actor else None,
            "player": actor.get("name") if actor else None,
            "detail": {"evidence_source": "provider_commentary"},
        })
        consumed.add(str(identifier))

    if added:
        supplemented = dict(game)
        supplemented["events"] = [*(game.get("events") or []), *added]
        selected = [event for event in build_events(supplemented) if is_backed(event)]

    # Provider may emit complementary statistics for the same foul:
    # player commits foul AND opponent is awarded a free kick. Reconcile into
    # one incident before placing its player at a contextual ball coordinate.
    from goodgame.foul_reconciliation import reconcile_fouls
    selected = reconcile_fouls(selected, game)

    # Commentary controls actors/roles/zones and linked corner deliveries.
    # Tracking may refine a named location, but cannot replace the narrative
    # actor with whichever player happens to be near a ball endpoint.
    from goodgame.commentary_spatial import enrich_replays
    return enrich_replays(game, selected)
