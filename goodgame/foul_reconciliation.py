"""Reconcile provider 'foul committed' and 'foul won' into one incident.

Two team statistics can describe the *same* infringement. Never merge merely
because the minute is equal: require shared commentary, matching participants,
or adjacent complementary opponent-sided narrations. Preserve provenance.
"""
from __future__ import annotations

import re
from typing import Any


def _mentions(text: str, players: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    lower = text.casefold()
    matches = []
    for player in players:
        name = str(player.get("name") or "").strip()
        if not name:
            continue
        match = re.search(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", lower)
        if match:
            matches.append((match.start(), player))
    return sorted(matches, key=lambda item: item[0])


def _identity(event: dict[str, Any]) -> str:
    return str(event.get("commentary_id") or "")


def _roles(comment: dict[str, Any] | None, players: list[dict[str, Any]]
           ) -> dict[str, Any]:
    text = str((comment or {}).get("comment") or "").casefold()
    parts = _mentions(text, players)
    offender = victim = None
    committed = bool(re.search(
        r"\b(?:fouls?|commits? a foul|concedes? a free kick|gives? away a free kick)\b",
        text,
    ))
    won = bool(re.search(
        r"\b(?:earns?|wins?|won|awarded|given|draws?)\b.{0,24}\bfree kick\b"
        r"|\b(?:is fouled|was fouled|has been fouled)\b", text,
    ))
    foul_verb = re.search(r"\bfouls?\b|\bcommits? a foul\b", text)
    if foul_verb:
        before = [player for pos, player in parts if pos < foul_verb.start()]
        after = [player for pos, player in parts if pos >= foul_verb.end()]
        if before:
            offender = before[-1]
        if after:
            victim = after[0]
    elif re.search(r"\b(?:foul|free kick)\s+(?:committed\s+)?by\b", text):
        by = re.search(r"\b(?:foul|free kick)\s+(?:committed\s+)?by\b", text)
        after = [p for pos, p in parts if pos >= by.end()]
        if after:
            offender = after[0]
    if won and parts and victim is None:
        victim = parts[0][1]
    if committed and parts and offender is None and not won:
        offender = parts[0][1]
    return {
        "offender": offender,
        "victim": victim,
        "committed": committed,
        "won": won,
        "mentions": {str(p.get("player_id")) for _, p in parts},
    }


def _same_incident(a: dict[str, Any], b: dict[str, Any],
                   comments: dict[str, dict[str, Any]],
                   players: list[dict[str, Any]]) -> bool:
    if a.get("minute") != b.get("minute"):
        return False
    if (
        a.get("extra_minute") is not None
        and b.get("extra_minute") is not None
        and a["extra_minute"] != b["extra_minute"]
    ):
        return False
    if (
        a.get("period_id") is not None and b.get("period_id") is not None
        and a["period_id"] != b["period_id"]
    ):
        return False
    aid, bid = _identity(a), _identity(b)
    if aid and aid == bid:
        return True
    ca, cb = comments.get(aid), comments.get(bid)
    if not ca or not cb:
        return False
    try:
        if abs(int(ca.get("sort_order")) - int(cb.get("sort_order"))) > 1:
            return False
    except (TypeError, ValueError):
        return False
    ra, rb = _roles(ca, players), _roles(cb, players)
    va, vb = ra["victim"], rb["victim"]
    oa, ob = ra["offender"], rb["offender"]
    if va and vb and str(va.get("player_id")) != str(vb.get("player_id")):
        return False
    if oa and ob and str(oa.get("player_id")) != str(ob.get("player_id")):
        return False
    # Player pair is explicitly shared between complementary descriptions.
    if va and vb and str(va.get("player_id")) == str(vb.get("player_id")):
        return True
    if oa and ob and str(oa.get("player_id")) == str(ob.get("player_id")):
        return True
    if ra["mentions"] & rb["mentions"] and (ra["committed"] != rb["committed"] or ra["won"] != rb["won"]):
        return True
    # One narrative says "X commits a foul" and the adjacent opposing-side
    # line says "Y wins a free kick". This is a weaker, but testable, link.
    if not (
        (ra["committed"] and rb["won"]) or (rb["committed"] and ra["won"])
    ):
        return False
    if a.get("team_id") is None or b.get("team_id") is None:
        return False
    return str(a["team_id"]) != str(b["team_id"])


def reconcile_fouls(
    events: list[dict[str, Any]], game: dict[str, Any],
) -> list[dict[str, Any]]:
    commentary = {
        str(row["id"]): row
        for row in game.get("commentary", []) or []
        if isinstance(row, dict) and row.get("id") is not None
    }
    players = [
        player for player in game.get("players", []) or []
        if isinstance(player, dict) and player.get("player_id") is not None
    ]
    fouls = [
        event for event in events
        if (event.get("spatial") or {}).get("kind") == "foul"
    ]
    groups: list[list[dict[str, Any]]] = []
    for foul in fouls:
        same = [group for group in groups
                if any(_same_incident(foul, item, commentary, players)
                       for item in group)]
        if not same:
            groups.append([foul])
        else:
            same[0].append(foul)
            for other in same[1:]:
                same[0].extend(other)
                groups.remove(other)

    replacement: dict[int, dict[str, Any]] = {}
    removed: set[int] = set()
    for group in groups:
        parsed = [
            (event, _roles(commentary.get(_identity(event)), players))
            for event in group
        ]
        # Favor the free-kick WINNER over the player who committed the foul.
        winner_events = [(ev, role) for ev, role in parsed if role["won"]]
        chosen = (winner_events or parsed)[0][0]
        counterpart = next((
            item["victim"] for _, item in parsed if item["victim"]
        ), None)
        offender = next((
            item["offender"] for _, item in parsed if item["offender"]
        ), None)
        detail = dict(chosen.get("detail") or {})
        related_ids = []
        for event in group:
            for cid in (event.get("commentary_id"),):
                if cid is not None and str(cid) not in list(map(str, related_ids)):
                    related_ids.append(cid)
        detail["foul_commentary_ids"] = related_ids
        detail["foul_event_ids"] = [
            ev.get("id") for ev in group if ev.get("id") is not None
        ]
        if counterpart is not None:
            detail["foul_victim_id"] = counterpart.get("player_id")
            detail["foul_victim_name"] = counterpart.get("name")
            chosen["player_id"] = counterpart.get("player_id")
            chosen["player"] = counterpart.get("name")
            if counterpart.get("team_id") is not None:
                chosen["team_id"] = counterpart["team_id"]
        if offender is not None:
            detail["foul_offender_id"] = offender.get("player_id")
            detail["foul_offender_name"] = offender.get("name")
        phases = []
        if offender:
            phases.append({
                "kind": "foul", "label": "Foul committed",
                "actor_id": offender.get("player_id"),
                "actor_name": offender.get("name"),
                "evidence": "provider_commentary",
            })
        if counterpart:
            phases.append({
                "kind": "free_kick", "label": "Free kick won",
                "actor_id": counterpart.get("player_id"),
                "actor_name": counterpart.get("name"),
                "evidence": "provider_commentary",
            })
        if phases:
            detail["event_sequence"] = phases
        chosen["detail"] = detail
        replacement[id(chosen)] = chosen
        removed.update(id(ev) for ev in group if ev is not chosen)
    return [replacement.get(id(ev), ev) for ev in events if id(ev) not in removed]
