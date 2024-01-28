import teamLink_PL23
import pandas as pd
import requests
from bs4 import BeautifulSoup


def playerLinks(HT):
    team_link = teamLink_PL23.TLink(HT)
    players_response = requests.get(f'{team_link}#tab:sqaud', 
                    headers={'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                   )
    players_soup = BeautifulSoup(players_response.text, 'lxml')
    
    squad = players_soup.find_all('div', class_='sc-fqkvVR dHiEKv')

    dict_plLinks = {}  # dictionary of Players in a team and their links
    players = []    #list of names of players
    pLinks = []     #list of links to player's profile
    
    for pl in squad:
        cat = pl.find_all('div', color='onSurface.nLv1')
        for p in cat:
            players.append(p.text.strip())
        links = pl.find_all('a', href=True)
        for l in links:
            pLinks.append(l.get('href'))

    for i in range(len(players)):
        dict_plLinks.update({players[i]: pLinks[i]})
    
    return dict_plLinks