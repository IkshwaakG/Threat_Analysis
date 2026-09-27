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
