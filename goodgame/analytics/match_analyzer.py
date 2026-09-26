"""Build evidence-backed match stories from provider incidents."""

from goodgame.models.event import Event
from goodgame.models.insight import Insight
from goodgame.models.match import Match


def _minute_label(minute: int | None) -> str:
    return f"{minute}'" if minute is not None else "minute unknown"


def _team_label(match: Match, event: Event) -> str:
    if event.is_home is True:
        return match.home_team.name
    if event.is_home is False:
        return match.away_team.name
    return "A team"


class MatchAnalyzer:
    def analyze(self, match: Match, events: list[Event]) -> tuple[Insight, ...]:
        insights = []
        ordered_events = sorted(
            enumerate(events, start=1),
            key=lambda item: (item[1].minute is None, item[1].minute or 0),
        )
        for index, event in ordered_events:
            category = event.incident_type
            minute = event.minute
            team = _team_label(match, event)
            evidence = (event.text,)

            if category == "goal":
                scorer = event.player or "Unknown scorer"
                score = (
                    f" Score: {event.home_score}-{event.away_score}."
                    if event.home_score is not None and event.away_score is not None
                    else ""
                )
                title = "Goal sequence"
                summary = f"{scorer} scored for {team} at {_minute_label(minute)}.{score}"
                impact = "high"
            elif category == "substitution":
                change = ""
                if event.player_in or event.player_out:
                    change = f" {event.player_in or 'Unknown player'} replaced {event.player_out or 'unknown player'}."
                title = "Substitution"
                summary = f"{team} made a substitution at {_minute_label(minute)}.{change}"
                impact = "medium"
            elif category == "card":
                card_type = str(event.incident_class or event.text).replace("_", " ").lower()
                card_label = card_type if card_type.endswith("card") else f"{card_type} card"
                title = "Red card" if "red" in card_type else "Card"
                player = f" to {event.player}" if event.player else ""
                summary = f"{team} received a {card_label}{player} at {_minute_label(minute)}."
                impact = "high" if "red" in card_type else "low"
            else:
                continue

            insights.append(
                Insight(
                    id=f"event-{event.id if event.id is not None else index}",
                    kind=category,
                    title=title,
                    impact=impact,
                    summary=summary,
                    start_minute=minute,
                    evidence=evidence,
                )
            )
        return tuple(insights)