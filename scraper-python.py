# scraper-python.py
# To run this script, paste `python scraper-python.py` in the terminal

import requests
from bs4 import BeautifulSoup

def scrape():
    url = 'https://store.steampowered.com/search/?filter=topsellers&os=win'
    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(response.text, 'html.parser')

    games = []
    for row in soup.select('.search_result_row'):
        games.append({
            'title': row.select_one('.title').text.strip(),
            'url': row['href'],
            'appid': row.get('data-ds-appid'),
            'release': row.select_one('.search_released').text.strip() if row.select_one('.search_released') else None,
            'price': row.select_one('.search_price').text.strip() if row.select_one('.search_price') else None,
        })

    for game in games[:100]:
        print(game)

if __name__ == '__main__':
    scrape()