"""Deterministic synthetic fixture, deliberately not presented as real GitHub data."""
import argparse
import json
import math
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from galaxy.render import render_gif


def fixture(stars):
    start = 1609459200
    # Includes a long quiet interval and a burst, to test history-driven births.
    counts = [stars // 20, stars // 10, stars // 4]
    counts.append(stars - sum(counts))
    return {'repository': 'example/synthetic-galaxy', 'created': start,
            'observed': start + 400 * 86400, 'stars': stars,
            'daily': [{'time': start + day * 86400, 'count': count}
                      for day, count in zip((10, 70, 290, 390), counts) if count]}


def smooth_fixture(stars):
    """A gradual, exact-total seven-year history for visual previews."""
    start = 1546300800
    days = 7 * 365
    weights = [0 if day < 7 else .3 + day / days + 2 * math.exp(-((day - days * .68) / 120) ** 2)
               for day in range(days)]
    raw = [stars * weight / sum(weights) for weight in weights]
    counts = [int(value) for value in raw]
    for index in sorted(range(days), key=lambda i: raw[i] - counts[i], reverse=True)[:stars - sum(counts)]:
        counts[index] += 1
    return {'repository': 'example/synthetic-galaxy', 'created': start,
            'observed': start + days * 86400, 'stars': stars,
            'daily': [{'time': start + day * 86400, 'count': count}
                      for day, count in enumerate(counts) if count]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stars', type=int, default=1000)
    parser.add_argument('--output', default='example.gif')
    parser.add_argument('--smooth', action='store_true', help='Use a gradual seven-year history')
    parser.add_argument('--width', type=int, default=800)
    args = parser.parse_args()
    start = time.perf_counter()
    result = render_gif((smooth_fixture if args.smooth else fixture)(args.stars), args.output, width=args.width)
    result['render_seconds'] = round(time.perf_counter() - start, 3)
    result['bytes'] = Path(args.output).stat().st_size
    Path(args.output).with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'frame_counts'}, indent=2))
