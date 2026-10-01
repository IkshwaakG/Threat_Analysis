# GoodGame Football Data

GoodGame is a football data and analytics project built around provider-independent match, team, player, and competition data.

Sportmonks Football API v3 is the default source for current football data. StatsBomb remains available for richer historical/open event data and analytics development.

## Current Architecture

```text
Sportmonks / StatsBomb
        ↓
provider-specific request layer
        ↓
response normalization
        ↓
GoodGame models
        ↓
GoodGamePipeline
        ↓
analytics / CLI / future API + VR clients
```

The provider abstraction allows GoodGame to switch data sources without coupling the analytics layer to one vendor.

## Setup

```sh
source .venv/bin/activate
pip install -r requirements.txt
export SPORTMONKS_API_TOKEN="your-sportmonks-token"
python -m goodgame
```

Do not commit API tokens. The Sportmonks token is sent through the `Authorization` header.

Use `python -m goodgame --help` to see available CLI options.

## Sportmonks Football API v3

Sportmonks is currently the default provider.

```text
goodgame/ingestion/sportmonks/
├── client.py
├── requests.py
├── responses.py
├── provider.py
└── PlayerStatsSampleResponse.json
```

- `client.py`: authentication, HTTP calls, errors, and pagination.
- `requests.py`: Sportmonks v3 endpoint definitions, filters, and `include=` chains.
- `responses.py`: raw response parsing and GoodGame normalization.
- `provider.py`: GoodGame-facing orchestration.

### Supported Sportmonks resources

The current integration covers:

- leagues, seasons, stages, rounds, and schedules
- teams, team search, teams by season/country, and squads
- team standings and season statistics
- players, player search, and player season statistics
- player statistics across all competitions in a season
- fixtures by ID, multiple IDs, date, range, team, search, and head-to-head
- latest-updated fixtures and live scores
- fixture events, lineups, statistics, scores, formations, venue, weather, coaches, and referees
- xG / expected data, lineup xG, pressure, ball coordinates, and expected lineups where available
- top scorers
- pre-match and post-match news
- match facts
- team of the week
- team rankings

Availability depends on the active Sportmonks plan and competition coverage.

## Fixture retrieval

Season-wide match selection uses:

```text
GET /schedules/seasons/{season_id}
```

The schedule payload can nest fixtures under stages, rounds, or groups. GoodGame recursively extracts and de-duplicates those fixtures.

For a selected match, GoodGame uses:

```text
GET /fixtures/{fixture_id}
```

### Lightweight vs detailed includes

Bulk listing requests intentionally stay small:

```text
SEASON_LIST_INCLUDES = league
FIXTURE_LIST_INCLUDES = participants;scores;state
```

A single fixture request uses the detailed include chain so GoodGame can retrieve richer match context without making every list request expensive.

That detailed response can include:

- events and event player/type data
- lineups and lineup details
- statistics
- formations
- xG fixture and lineup data
- scores
- periods
- participants
- venue and weather
- coaches and referees
- pressure
- ball coordinates
- expected lineups
- metadata and sidelined players
- match news
- odds/predictions when the account permits them

## Player statistics

Player requests include nested statistics data such as:

```text
statistics.details.type
statistics.team
statistics.season.league
```

GoodGame can narrow player statistics server-side with:

```text
playerstatisticSeasons:<season_id>
```

By default, player season statistics can aggregate across all competitions in that season. Supplying a competition ID narrows the result to one competition.

Player search also includes fallback handling for abbreviated names such as `K. Schmeichel`.

## Team statistics

GoodGame combines standings with season team statistics:

```text
GET /standings/seasons/{season_id}
GET /statistics/seasons/teams/{team_id}
```

This keeps league position/points and richer season statistics available independently.

## Match-level data

For one fixture, GoodGame can expose:

- normalized match metadata
- events
- lineups
- fixture statistics
- xG
- pressure
- ball coordinates

The analytics layer should consume normalized GoodGame data rather than provider-specific payloads directly.

## Postman

The repository includes:

```text
postman/
├── GoodGame-Sportmonks.postman_collection.json
└── GoodGame-Sportmonks.postman_environment.json
```

Import both files into Postman and set `sportmonks_token` in the environment. The collection mirrors important request paths used by the Python integration and is useful for inspecting raw Sportmonks responses.

## StatsBomb

StatsBomb remains available as a secondary provider for:

- historical Open Data
- detailed events
- spatial event and shot coordinates
- xG
- analytics development
- derived team/player statistics

Example:

```sh
python -m goodgame \
  --provider statsbomb \
  --competition-id 9 \
  --season-id 281 \
  --match-id 3895232
```

StatsBomb Open Data contains selected competitions/seasons only. Authenticated access can use `SB_USERNAME` and `SB_PASSWORD`, subject to the account/license.

## Switching providers

Sportmonks is the default.

```sh
python -m goodgame --provider sportmonks
python -m goodgame --provider statsbomb
```

Or:

```sh
export GOODGAME_PROVIDER=statsbomb
python -m goodgame
```

## Tests

```sh
python -m unittest discover -s tests -v
```

The Sportmonks tests cover endpoint routing, include chains, schedule fixture extraction, player search fallback, team/player statistics, and provider integration.

## Next direction

The ingestion layer should ultimately feed persistent storage instead of repeatedly querying providers for every analytics request.

```text
Sportmonks / StatsBomb
        ↓
raw ingestion
        ↓
GCP storage
        ↓
normalized GoodGame data
        ↓
analytics engine
        ↓
API
        ↓
Web / Quest
```

The next major step is defining the GCP persistence model and normalized schemas, then building evidence-backed GoodGame analyzers on top.


## Deployable GoodGame application

The repositories stay separate:

- football_xT_FE: frontend development
- Threat_Analysis: deployable GoodGame backend/application
- football_xT_ETL: independent Sportmonks-to-BigQuery ingestion

The ETL repo is not packaged into the web application.

Runtime flow:

Browser -> "/" -> compiled React assets
Browser -> "/api/*" -> FastAPI -> serving repository

The serving repository is selected with DATA_MODE:

- DATA_MODE=gcp -> BigQuery
- DATA_MODE=demo -> demo_data/snapshot.json

The frontend API contract is identical in both modes.

### Local GCP mode

Set DATA_MODE=gcp, GCP_PROJECT_ID=gg-football-data and BIGQUERY_CORE_DATASET=football_core, then run:

uvicorn goodgame.web:app --reload --port 8000

The frontend dev server can still run separately and proxy /api to port 8000.

### Build one deployable application

With football_xT_FE and Threat_Analysis checked out next to each other, run from Threat_Analysis:

bash scripts/package_frontend.sh ../football_xT_FE

This builds football_xT_FE/apps/web/dist and copies only the compiled files into Threat_Analysis/static.

Then run:

DATA_MODE=gcp uvicorn goodgame.web:app --host 0.0.0.0 --port 8000

Opening http://localhost:8000/ loads the website. The JSON APIs are served under /api on the same origin.

### Demo mode

Create a packaged snapshot from normalized GCP data using:

python scripts/export_demo_snapshot.py --competition-id <league_id> --season-id <season_id> --fixture-id <fixture_id> --team-id <team_id> --player-id <player_id>

Then run:

DATA_MODE=demo uvicorn goodgame.web:app --host 0.0.0.0 --port 8000

Demo mode does not query BigQuery at request time.

### Docker / Cloud Run style deployment

After packaging the frontend:

docker build -t goodgame .
docker run --rm -p 8080:8080 -e DATA_MODE=demo goodgame

Health check: GET /api/health

For GCP-backed deployment use DATA_MODE=gcp and give the runtime service account BigQuery read permissions.

The runtime image contains Python backend code, compiled frontend assets, and optional demo snapshot data. It does not contain frontend source, node_modules, Vite dev tooling, or the ETL/Sportmonks ingestion repo.


## Current V1 serving contract

The frontend-serving path is database-only:

```text
football_xT_FE
    ↓ /api/*
Threat_Analysis
    ↓
football_core
```

The web service does not read `football_raw` and does not call Sportmonks.
Raw provider payloads are ETL-only.

### Cost rules

Game/fixture screens use:

```text
GET /api/games/{fixture_id}
```

That response contains the fixture, teams, lineup players, fixture player/team
statistics, facts, events, timeline, spatial/event data and profile links needed
for the current screen. Player selection is frontend-local and must not trigger
another API/BigQuery request.

Team and Player profile pages each use one detailed endpoint:

```text
GET /api/teams/{team_id}?season_id=...&competition_id=...
GET /api/players/{player_id}?season_id=...&competition_id=...
```

Global player/team search is explicit-submit only:

```text
GET /api/search?q=...&season_id=...&competition_id=...
```

The UI does not query on each search keystroke.

### Core-only fixture facts

Match facts that were previously read from raw provider JSON are now expected in
normalized core tables:

- `football_core.fixture_facts`
- `football_core.standings`
- `football_core.fixture_scores`
- `football_core.fixture_timeline`
- `football_core.venues`
- `football_core.fixture_weather`
- `football_core.fixture_sidelined`

Run the ETL core transform after pulling these changes before testing GCP mode.

### Demo verification

The repository contains a fully functional sanitized example snapshot:

```bash
python scripts/verify_demo_snapshot.py \
  --snapshot demo_data/snapshot.example.json
```

To run the application in demo mode using that example locally:

```bash
cp demo_data/snapshot.example.json demo_data/snapshot.json
DATA_MODE=demo uvicorn goodgame.web:app --port 8000
```

A real demo snapshot can still be generated from GCP using
`scripts/export_demo_snapshot.py`, then verified with the same command.
