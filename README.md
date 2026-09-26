# GoodGame football data

GoodGame can use Sportmonks for current fixtures and StatsBomb for open historical event data. Sportmonks is the default provider.

## Sportmonks

The token previously pasted into chat should be revoked and replaced. Set the rotated token locally in your shell; do not paste it into chat or commit it:

```sh
source .venv/bin/activate
pip install -r requirements.txt
export SPORTMONKS_API_TOKEN="your-rotated-sportmonks-token"
python -m goodgame
```

Choose a competition and season, then select a fixture. For a known Sportmonks fixture ID:

```sh
python -m goodgame --provider sportmonks --match-id FIXTURE_ID
```

The integration uses Sportmonks Football API v3. It requests fixture details, participants, scores, events, lineups, statistics, and fixture expected-goal data where available. Actual includes and coverage depend on your plan; the token is sent in the `Authorization` header, not the URL. Spatial event/shot detail is not yet normalized or guaranteed by this adapter.

## Switch Providers

Set `GOODGAME_PROVIDER` to change the default, or use `--provider` for one run:

```sh
export GOODGAME_PROVIDER=statsbomb
python -m goodgame
python -m goodgame --provider sportmonks
```

StatsBomb remains available for historical Open Data and its team/player season aggregations. Both providers support team season stats. Sportmonks player stats use the account-visible player search and nested season statistics; available metrics vary by subscription.

```sh
python -m goodgame --provider statsbomb --competition-id 9 --season-id 281 --match-id 3895232
python -m goodgame --provider statsbomb --team-stats "Bayer Leverkusen" --competition-id 9 --season-id 281
python -m goodgame --provider statsbomb --player-stats "Florian Wirtz" --competition-id 9 --season-id 281
```

StatsBomb Open Data only contains a limited set of historical competitions. Authenticated StatsBomb credentials can be configured separately with `SB_USERNAME` and `SB_PASSWORD`; access remains subject to your license.

Run tests with `python -m unittest discover -s tests -v`. Use `python -m goodgame --help` for CLI options.
