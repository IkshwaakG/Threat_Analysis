"""Orchestrate one-match ingestion and analysis."""

from goodgame.analytics.match_analyzer import MatchAnalyzer
from goodgame.ingestion.sofascore.client import SofaScoreClient
from goodgame.ingestion.sofascore.events import fetch_match_events
from goodgame.ingestion.sofascore.lineups import fetch_lineups
from goodgame.ingestion.sofascore.matches import fetch_match
from goodgame.ingestion.sofascore.shots import fetch_shot_map
from goodgame.models.insight import MatchAnalysis


class GoodGamePipeline:
    def __init__(
        self,
        client: SofaScoreClient | None = None,
        analyzer: MatchAnalyzer | None = None,
    ) -> None:
        self.client = client or SofaScoreClient()
        self.analyzer = analyzer or MatchAnalyzer()

    def analyze_match(self, match_id: int) -> MatchAnalysis:
        match = fetch_match(self.client, match_id)
        events = fetch_match_events(self.client, match_id)
        lineups = fetch_lineups(self.client, match_id)
        shots = fetch_shot_map(self.client, match_id)
        return MatchAnalysis(
            match=match,
            events=tuple(events),
            insights=self.analyzer.analyze(match, events),
            lineups=lineups,
            shots=tuple(shots),
        )