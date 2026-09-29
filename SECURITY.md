# Security

## Secrets

Do not commit API tokens, service-account JSON files, private keys, or local
environment files. The repository .gitignore blocks common secret filenames,
but deployment secrets must still be supplied through the runtime environment
or a managed secret store.

The public web runtime must never receive SPORTMONKS_API_TOKEN or StatsBomb
credentials. Provider credentials belong only to ingestion/development jobs.

## GCP identities

Use separate service accounts:

- GoodGame web/Cloud Run: BigQuery query execution plus read-only access to the
  required football_core tables.
- ETL: only the dataset/table write and provider-ingestion permissions required
  by the ingestion jobs.

The web identity must not have write access to football_core or access to
football_raw.

## Query abuse controls

The serving repository applies a maximum bytes billed value and query timeout.
Production deployments should tune:

- GOODGAME_BIGQUERY_MAX_BYTES_BILLED
- GOODGAME_BIGQUERY_TIMEOUT_SECONDS
- GOODGAME_RATE_LIMIT_PER_MINUTE

Internet-facing deployments should also enforce rate limits at the managed
edge/gateway layer. The in-process limiter is only a defense-in-depth control.

## Demo data

demo_data/snapshot.json is generated and ignored by Git. Do not commit real demo
snapshots to this public repository. Commit only sanitized examples.

## Production HTTP

Set GOODGAME_ENV=production. Production mode disables FastAPI docs by default
and enables browser security headers. GOODGAME_ENABLE_DOCS=true can explicitly
re-enable API docs when required.

## Reporting

If a secret is ever committed, revoke/rotate it first. Removing it from the
latest commit is not sufficient because Git history may still contain it.
