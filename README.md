# GoodGame data foundation

Install the provider dependency with `python -m pip install -r requirements.txt`.

Discover matches for any SofaScore tournament and season, then analyze a selected match:

```python
from goodgame.ingestion.sofascore.client import SofaScoreClient
from goodgame.ingestion.sofascore.matches import fetch_season_matches
from goodgame.pipeline import GoodGamePipeline

client = SofaScoreClient()
matches = fetch_season_matches(client, tournament_id=17, season_id=52186)
print([(match.id, match.home_team.name, match.away_team.name) for match in matches])

analysis = GoodGamePipeline(client).analyze_match(match_id=YOUR_MATCH_ID)
for insight in analysis.insights:
    print(insight.start_minute, insight.title, insight.summary)
```

The pipeline retrieves match details, incidents, lineups, and shot-map data. Its initial story rules report supported goals, substitutions, and cards; they do not infer tactical causes from aggregate statistics. `MatchAnalysis` keeps the normalized match, events, insights, lineups, and shots together for later API or visualization use.

`goodgame/ingestion/sofascore/players.py` and `teams.py` contain the generic squad, profile-link, and statistics helpers. Their default competition and season are Premier League 2023-24; pass `tournament_id` and `season_id` for another competition or season.

Run the tests with `python -m unittest discover -s tests -v` after installing requirements. SofaScore may change or restrict its public API, so provider endpoint compatibility should be verified against an accessible match before production use.