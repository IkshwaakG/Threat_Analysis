import requests
import playersLink_PL23

pL = playersLink_PL23.playerLinks(HT= input("Enter Team:"))
print (pL)
player1 = input("Enter Player from above:")

def playerStats(player):

#https://api.sofascore.com/api/v1/player/934235/unique-tournament/17/season/52186/statistics/overall
    
    playerId = pL[player].split('/')[3]

    plStatLink_23 = f'https://api.sofascore.com/api/v1/player/{playerId}/unique-tournament/17/season/52186/statistics/overall'

    player_stats23_resp = requests.get(plStatLink_23,
                            headers={'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                            )
    player_stats23 = player_stats23_resp.json()['statistics']

    return player_stats23

print(playerStats(player1))