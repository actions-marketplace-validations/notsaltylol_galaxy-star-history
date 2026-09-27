"""GitHub API snapshot validation. Never rescale, sample, or invent stars."""
import json
import re
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API = 'https://api.github.com'
MAX_STARS = 1_000_000


def timestamp(value):
    return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())


def validate_repository(repository):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+', repository):
        raise ValueError('repository must be owner/repo')
    return repository


def request_json(path, token):
    headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2026-03-10',
               'User-Agent': 'galaxy-star-history-action'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    for attempt in range(3):
        try:
            with urlopen(Request(API + path, headers=headers), timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise ValueError(f'GitHub API HTTP {error.code} at {path}; check token access and rate limits') from None
        except URLError:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise ValueError('Unable to connect to GitHub API') from None


def validate_snapshot(data):
    validate_repository(data['repository'])
    stars = data['stars']
    if type(stars) is not int or not 0 <= stars <= MAX_STARS:
        raise ValueError(f'Current stars must be between 0 and {MAX_STARS:,}; sampling is never used')
    if type(data['created']) is not int or type(data['observed']) is not int or data['created'] > data['observed']:
        raise ValueError('Invalid snapshot dates')
    previous = -1
    total = 0
    for day in data['daily']:
        if type(day['time']) is not int or day['time'] <= previous:
            raise ValueError('History dates must be unique and ascending')
        if type(day['count']) is not int or day['count'] < 0:
            raise ValueError('Daily star counts must be nonnegative integers')
        if day['count'] and day['time'] > data['observed']:
            raise ValueError('History contains future stars')
        previous = day['time']
        total += day['count']
    if total != stars:
        raise ValueError(f'Exact-count check failed: history contains {total:,} stars, current count is {stars:,}. '
                         'GitHub may be updating or the history may differ from current stars. '
                         'Refusing to invent, discard, or rescale stars; retry later.')
    return data


def fetch_snapshot(repository, token='', get=None):
    validate_repository(repository)
    get = get or (lambda path: request_json(path, token))
    # Re-fetch once when the paginated history and count were read during a change.
    for attempt in range(2):
        metadata = get(f'/repos/{repository}')
        daily = []
        for page in range(1, 101):
            batch = get(f'/repos/{repository}/stargazers/history?per_page=30&page={page}')
            if not isinstance(batch, list):
                raise ValueError('Invalid history response')
            for week in batch:
                days = week.get('days')
                if (type(week.get('week')) is not int or not isinstance(days, list) or len(days) != 7
                        or any(type(n) is not int or n < 0 for n in days)
                        or sum(days) != week.get('total')):
                    raise ValueError('Invalid weekly history data')
                daily.extend({'time': week['week'] + i * 86400, 'count': count} for i, count in enumerate(days) if count)
            if len(batch) < 30:
                break
            if page == 100:
                raise ValueError('History exceeds API pagination limit')
        current = get(f'/repos/{repository}/stargazers/count')['count']
        snapshot = {'repository': repository, 'created': timestamp(metadata['created_at']),
                    'observed': int(datetime.now(timezone.utc).timestamp()),
                    'stars': current, 'daily': sorted(daily, key=lambda d: d['time'])}
        if sum(d['count'] for d in daily) == current or attempt:
            return validate_snapshot(snapshot)
    raise AssertionError('unreachable')
