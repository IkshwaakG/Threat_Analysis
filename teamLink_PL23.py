import requests
import pandas as pd


# https://api.sofascore.com/api/v1/unique-tournament/17/season/52186/standings/total ---> SofaScore API for PL'23-24.

teams_response = requests.get('https://api.sofascore.com/api/v1/unique-tournament/17/season/52186/standings/total',
                        headers={'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                        )

# the headers field will vary for each user and is included to prevent the server from interpreting the user as a bot.

standings = teams_response.json()['standings']
df_standings = pd.DataFrame(standings)
teams = standings[0]['rows']
df_teams = pd.DataFrame(teams)
teamLink_23 = {}

for i in range(20):
    slug = teams[i]['team']['slug']
    team_id = teams[i]['team']['id']
    link = f'https://sofascore.com/team/football/{slug}/{team_id}'
    teamLink_23.update({teams[i]['team']['name']: link})

def TLink(team):
    return(teamLink_23[team])
