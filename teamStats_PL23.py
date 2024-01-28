import teamLink_PL23
import requests


def teamStats(HT):
    tL = teamLink_PL23.TLink(HT)
    teamId = tL[-2:]

#https://api.sofascore.com/api/v1/team/{teamId}/unique-tournament/{tournamentId}/season/{seasonId}/statistics/overall
#17 ---> Premier League,52186 ---> 2023-24 season
    teamStatLink_23 = f'https://api.sofascore.com/api/v1/team/{teamId}/unique-tournament/17/season/52186/statistics/overall'
    team_stats_resp23 = requests.get(teamStatLink_23,
                            headers={'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                            )
    
    team_stats23 = team_stats_resp23.json()['statistics']

    return team_stats23
