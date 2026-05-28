# scraper-python.py
# To run this script, paste `python scraper-python.py` in the terminal

import requests
from bs4 import BeautifulSoup


def scrape():
    
    url = 'https://steamdb.info/stats/gameratings/?min_reviews=500'
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    print(soup)



if __name__ == '__main__':
    scrape()