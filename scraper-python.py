# scraper-python.py
# To run this script, paste `python scraper-python.py --max 100 --outfile results.json` in the terminal

import argparse
import time
import re
import json
import csv
import requests
from datetime import datetime
from bs4 import BeautifulSoup


def fetch_soup(url):
    resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    resp.raise_for_status()
    return BeautifulSoup(resp.text, 'html.parser')


def scrape_game_page(url):
    """Fetch a Steam game/store page and try to extract current price, original price, and discount percent."""
    try:
        soup = fetch_soup(url)
    except Exception:
        return {'current_price': None, 'original_price': None, 'discount_pct': None}

    # discount percent (examples: '-25%', '25%')
    discount_elem = soup.select_one('.discount_pct') or soup.select_one('.discount_block .percentage')
    discount = discount_elem.text.strip() if discount_elem else None

    # current / final price
    final = soup.select_one('.discount_final_price') or soup.select_one('.game_purchase_price') or soup.select_one('.game_area_purchase_price') or soup.select_one('.price')
    current_price = final.text.strip() if final else None

    # original / stricken price when discounted
    original = soup.select_one('.discount_original_price') or soup.select_one('.discount_old_price') or soup.select_one('.original_price')
    original_price = original.text.strip() if original else None

    # Normalize discount string (remove leading - and ensure 'off')
    if discount:
        m = re.search(r'(-?\d+)%', discount)
        if m:
            discount = f"{m.group(1)}% off"

    # release date (store page)
    release_elem = soup.select_one('.release_date .date') or soup.select_one('.date')
    release_date = release_elem.text.strip() if release_elem else None

    return {
        'current_price': current_price,
        'original_price': original_price,
        'discount_pct': discount,
        'release_date': release_date,
    }


def scrape_listing(url, limit=100, pause=0.5):
    games = []
    page = 1
    while len(games) < limit:
        sep = '&' if '?' in url else '?'
        page_url = f"{url}{sep}page={page}"
        try:
            soup = fetch_soup(page_url)
        except Exception:
            break

        rows = soup.select('.search_result_row')
        if not rows:
            break

        for row in rows:
            title_elem = row.select_one('.title')
            title = title_elem.text.strip() if title_elem else None
            link = row.get('href') or (row.select_one('a')['href'] if row.select_one('a') else None)
            appid = row.get('data-ds-appid')
            release = row.select_one('.search_released').text.strip() if row.select_one('.search_released') else None

            game = {
                'title': title,
                'url': link,
                'appid': appid,
                'release': release,
            }

            # If we have a specific game URL, fetch its page to get accurate price, discount and release date
            if link:
                try:
                    details = scrape_game_page(link)
                    game.update(details)
                except Exception:
                    game.update({'current_price': None, 'original_price': None, 'discount_pct': None, 'release_date': None})
                time.sleep(pause)

            # Get current player count via Steam public API if we have an appid
            player_count = None
            if appid:
                try:
                    api = requests.get('https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/', params={'appid': appid}, headers={'User-Agent': 'Mozilla/5.0'})
                    api.raise_for_status()
                    data = api.json()
                    player_count = data.get('response', {}).get('player_count')
                except Exception:
                    player_count = None
                # small pause after API call
                time.sleep(pause)

            game['current_players'] = player_count
            game['scraped_at'] = datetime.utcnow().isoformat()

            games.append(game)
            if len(games) >= limit:
                break

        page += 1

    return games


def main():
    parser = argparse.ArgumentParser(description='Simple Steam scraper: listing or single game page')
    parser.add_argument('--url', '-u', help='Steam URL to scrape', default='https://store.steampowered.com/search/?filter=topsellers')
    parser.add_argument('--max', '-m', type=int, default=100, help='Maximum number of games to fetch from a listing (default 100)')
    parser.add_argument('--pause', '-p', type=float, default=0.5, help='Pause (seconds) between requests')
    parser.add_argument('--outfile', '-o', help='Write output to file (JSON or CSV based on --format)')
    parser.add_argument('--format', '-f', choices=['json', 'csv'], default='json', help='Output format when using --outfile')
    args = parser.parse_args()

    url = args.url

    # If the URL looks like a single app/sub page, just scrape that page
    if '/app/' in url or '/sub/' in url:
        result = scrape_game_page(url)
        print({'url': url, **result})
        return

    # Otherwise treat it as a listing page
    games = scrape_listing(url, limit=args.max, pause=args.pause)

    # Print and optionally save
    if args.outfile:
        if args.format == 'json':
            # If outfile exists and contains previous data, merge by game key
            try:
                with open(args.outfile, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except FileNotFoundError:
                existing = None
            except Exception:
                # If file exists but is malformed, don't crash — overwrite
                existing = None

            # Normalize existing data into dict: key -> list of snapshots
            data = {}
            if isinstance(existing, list):
                for item in existing:
                    key = item.get('appid') or item.get('title')
                    data.setdefault(key, []).append(item)
            elif isinstance(existing, dict):
                # assume dict of lists already
                data = existing

            # Append new games
            for g in games:
                key = g.get('appid') or g.get('title')
                data.setdefault(key, []).append(g)

            with open(args.outfile, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            # write CSV using keys from first item
            keys = set()
            for g in games:
                keys.update(g.keys())
            keys = list(keys)
            with open(args.outfile, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                for g in games:
                    writer.writerow(g)
        print(f'Wrote {len(games)} items to {args.outfile}')
    else:
        for g in games:
            print(g)


if __name__ == '__main__':
    main()