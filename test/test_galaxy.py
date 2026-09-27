import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image
from galaxy.history import fetch_snapshot, validate_snapshot
from galaxy.render import frame_state, particles, project, render_gif
from examples.generate import fixture


class AccuracyTests(unittest.TestCase):
    def test_every_star_has_a_point_up_to_one_million(self):
        for n in (0, 1, 1000, 500000, 1000000):
            with self.subTest(n=n):
                data = fixture(n)
                x, y, brightness, births = particles(data)
                self.assertEqual([len(v) for v in (x, y, brightness, births)], [n] * 4)
                states = [frame_state(data, births, f, 150, 15, 30) for f in range(150)]
                counts = [s[0] for s in states]
                self.assertEqual(counts[0], 0)
                self.assertEqual(counts[-1], n)
                self.assertEqual(sorted(counts), counts)
                for count, when, _ in states[1:]:
                    self.assertEqual(count, sum(d['count'] for d in data['daily'] if d['time'] <= when))
                times = np.array([round(f * 100 / 15) / 100 for f in range(150)])
                np.testing.assert_allclose(np.diff([s[2] for s in states]) / np.diff(times), 2 * math.pi / 30, rtol=1e-12)

    def test_no_points_are_clipped_or_dropped(self):
        data = fixture(1000000)
        x, y, _, _ = particles(data)
        for angle in np.linspace(0, 2 * math.pi, 12):
            indices = project(x, y, len(x), angle, 800, 530)
            density = np.bincount(indices, minlength=800 * 530)
            self.assertEqual(int(density.sum()), 1000000)

    def test_mismatch_and_oversize_are_errors_not_sampling(self):
        data = fixture(1000)
        data['stars'] += 1
        with self.assertRaisesRegex(ValueError, 'Exact-count'):
            particles(data)
        with self.assertRaisesRegex(ValueError, 'sampling is never used'):
            particles(fixture(1000001))

    def test_deterministic_geometry(self):
        data = fixture(1000)
        for first, second in zip(particles(data), particles(data)):
            np.testing.assert_array_equal(first, second)

    def test_gif_decodes_and_report_reaches_actual_total(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'galaxy.gif'
            report = render_gif(fixture(1000), path, width=400, fps=5, duration=4)
            self.assertEqual(report['first_frame_stars'], 0)
            self.assertEqual(report['last_frame_stars'], 1000)
            with Image.open(path) as image:
                self.assertEqual(image.format, 'GIF')
                self.assertEqual(image.info['loop'], 0)
                self.assertEqual(image.size, (400, 265))
                elapsed = 0
                for i in range(image.n_frames):
                    image.seek(i)
                    image.load()
                    elapsed += image.info['duration']
                self.assertEqual(elapsed, 4000)


class GitHubTests(unittest.TestCase):
    def test_paginated_history_and_count_endpoint(self):
        calls = []
        def get(path):
            calls.append(path)
            if path.endswith('/count'):
                return {'count': 31}
            if '/history?' in path:
                page = 2 if 'page=2' in path else 1
                count = 30 if page == 1 else 1
                return [{'week': 1609632000 + ((30 - i) if page == 1 else 0) * 604800,
                         'total': 1, 'days': [1, 0, 0, 0, 0, 0, 0]} for i in range(count)]
            return {'created_at': '2021-01-01T00:00:00Z'}
        data = fetch_snapshot('owner/repo', get=get)
        self.assertEqual(data['stars'], 31)
        self.assertEqual(sum(d['count'] for d in data['daily']), 31)
        self.assertTrue(any('page=2' in c for c in calls))
        self.assertTrue(calls[-1].endswith('/count'))

    def test_mismatch_retries_and_fails(self):
        counts = []
        def get(path):
            if path.endswith('/count'):
                counts.append(path)
                return {'count': 1}
            if '/history?' in path:
                return []
            return {'created_at': '2021-01-01T00:00:00Z'}
        with self.assertRaisesRegex(ValueError, 'Refusing to invent'):
            fetch_snapshot('owner/repo', get=get)
        self.assertEqual(len(counts), 2)

    def test_duplicate_days_rejected(self):
        data = fixture(1000)
        data['daily'].append(data['daily'][-1])
        with self.assertRaisesRegex(ValueError, 'unique'):
            validate_snapshot(data)


if __name__ == '__main__':
    unittest.main()
