"""Orchestrate one-match ingestion and analysis."""

from collections.abc import Sequence

from goodgame.analytics.match_analyzer import MatchAnalyzer
from goodgame.ingestion.provider import MatchDataProvider
from goodgame.models.insight import MatchAnalysis


class GoodGamePipeline:
    def __init__(
        self,
        provider: MatchDataProvider,
        analyzers: Sequence[MatchAnalyzer] | None = None,
    ) -> None:
        self.provider = provider
        if analyzers is not None:
            self.analyzers = tuple(analyzers)
        else:
            self.analyzers = (MatchAnalyzer(),)

    def analyze_match(self, match_id: int) -> MatchAnalysis:
        match = self.provider.get_match(match_id)
        events = self.provider.get_events(match_id)
        insights = tuple(
            insight
            for current_analyzer in self.analyzers
            for insight in current_analyzer.analyze(match, events)
        )
        return MatchAnalysis(
            match=match,
            events=tuple(events),
            insights=insights,
            lineups=self.provider.get_lineups(match_id),
            shots=tuple(self.provider.get_shot_map(match_id)),
        )