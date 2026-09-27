import copy
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw
from galaxy.history import fetch_snapshot, validate_snapshot
from galaxy.__main__ import main
from galaxy.render import (GROWTH, MAX_TRAILS, TRANSPARENT, clip_time, fit_label, font, frame_state, growth_progress,
                           particles, prepare, project, render_frame, render_gif, star_colors, trail_splats)
from examples.generate import fixture


class AccuracyTests(unittest.TestCase):
    def test_every_star_has_a_point_up_to_one_million(self):
        for n in (0, 1, 1000, 500000, 1000000):
            with self.subTest(n=n):
                data = fixture(n)
                x, y, brightness, births = particles(data)
                self.assertEqual([len(v) for v in (x, y, brightness, births)], [n] * 4)
                # The fixture was observed after its last star day.
                last_star_day = max([data['created']] + [d['time'] for d in data['daily']])
                self.assertLess(last_star_day, data['observed'])
                states = [frame_state(data, births, last_star_day, f, 150, 15, 30) for f in range(150)]
                counts = [s[0] for s in states]
                self.assertEqual(counts[0], 0)
                self.assertEqual(counts[-1], n)
                self.assertEqual(sorted(counts), counts)
                for frame, (count, when, _) in enumerate(states):
                    if growth_progress(frame, 150) == 1:
                        # The held, finished galaxy shows every star, dated the last star day.
                        self.assertEqual((count, when), (n, last_star_day))
                    elif count == 0:
                        self.assertEqual(when, data['created'])
                    else:
                        # Stars arrive in history order: the count lies within the day bucket shown.
                        before = sum(d['count'] for d in data['daily'] if d['time'] < when)
                        through = sum(d['count'] for d in data['daily'] if d['time'] <= when)
                        self.assertLess(before, count)
                        self.assertLessEqual(count, through)
                # The current count is reached GROWTH of the way through the clip.
                growing = sum(growth_progress(f, 150) < 1 for f in range(150))
                self.assertAlmostEqual(growing / (150 - 1), GROWTH, delta=.01)
                # Growth is linear in stars, so the galaxy is never left nearly empty for most of the clip.
                mid = states[len(states) // 4][0]
                # (Within half a star for tiny histories, where a 2% tolerance is below one star.)
                self.assertLessEqual(abs(mid - n / 2), max(.02 * n, .5))
                times = np.array([clip_time(f, 15) for f in range(150)])
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

    def test_effects_scale_with_star_count(self):
        for n in (39, 1000, 1000000):
            with self.subTest(n=n):
                data = fixture(n)
                particle_data = particles(data)
                x, y, brightness, _ = particle_data
                trails = prepare(data, particle_data, 800, 530)['trails']
                self.assertLessEqual(len(trails), MAX_TRAILS)
                indices, weights = trail_splats(x, y, brightness, star_colors(x, y), trails, n, .3, 5.0, 30, 800, 530)
                self.assertEqual(len(indices), len(weights))
                if n == 39:
                    # Fewer than 40 stars earn no trail.
                    self.assertEqual(len(trails), 0)
                    self.assertEqual(len(indices), 0)
                else:
                    self.assertGreater(len(trails), 0)
                    self.assertGreater(len(indices), 0)
                    self.assertTrue((weights > 0).any())
                    self.assertLess(int(indices.max()), 800 * 530)

    def test_long_repository_names_are_truncated_to_fit(self):
        draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        self.assertEqual(fit_label(draw, 'owner/repo', 12, 400), 'owner/repo')
        name = 'an-organization-with-a-long-name/' + 'a-repository-name-that-keeps-going-' * 4
        for size, width in ((12, 460), (9, 180), (18, 700), (12, 20)):
            with self.subTest(size=size, width=width):
                label = fit_label(draw, name, size, width)
                self.assertTrue(label.endswith('…'))
                self.assertTrue(name.startswith(label[:-1]))
                self.assertLessEqual(draw.textlength(label, font=font(size)), width)
                # The longest prefix that fits: one more character would overflow.
                longer = name[:len(label)] + '…'
                self.assertGreater(draw.textlength(longer, font=font(size)), width)
        self.assertEqual(fit_label(draw, name, 12, 3), '')

    def test_frame_differencing_is_lossless(self):
        # Transparent unchanged pixels must composite back to exactly the rendered frames.
        data = fixture(1000)
        particle_data = particles(data)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'galaxy.gif'
            report = render_gif(data, path, width=400, fps=5, duration=4)
            width, height = report['width'], report['height']
            scene = prepare(data, particle_data, width, height)
            with Image.open(path) as image:
                self.assertEqual(image.n_frames, report['frames'])
                palette = Image.new('P', (1, 1))
                palette.putpalette(image.getpalette()[:3 * TRANSPARENT])
                for frame in range(image.n_frames):
                    image.seek(frame)
                    rendered, _ = render_frame(data, particle_data, scene, frame, report['frames'], report['fps'],
                                               report['rotation_period'], width, height)
                    expected = rendered.quantize(palette=palette, dither=Image.Dither.NONE).convert('RGB')
                    np.testing.assert_array_equal(np.asarray(image.convert('RGB')), np.asarray(expected))

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


class ActionTests(unittest.TestCase):
    def test_output_is_stable_across_days_until_the_history_changes(self):
        history = fixture(1000)
        fetches = iter(range(10))
        def fetch(repository, token):
            # Every run fetches on a later day; only the star history decides the output.
            data = copy.deepcopy(history)
            data['observed'] = history['observed'] + next(fetches) * 86400
            return data
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = root / 'github_output'
            env = {'GITHUB_WORKSPACE': directory, 'GITHUB_OUTPUT': str(outputs),
                   'INPUT_REPOSITORY': 'example/synthetic-galaxy', 'INPUT_TOKEN': '',
                   'INPUT_OUTPUT': 'images/galaxy.gif', 'INPUT_WIDTH': '400', 'INPUT_FPS': '5',
                   'INPUT_DURATION': '4', 'INPUT_ROTATION_PERIOD': '30'}
            gif, manifest = root / 'images' / 'galaxy.gif', root / 'images' / 'galaxy.json'
            def run():
                outputs.unlink(missing_ok=True)
                with patch.dict(os.environ, env), patch('galaxy.__main__.fetch_snapshot', side_effect=fetch), \
                        patch('builtins.print'):
                    main()
                lines = dict(line.split('=', 1) for line in outputs.read_text().splitlines())
                return lines['changed'], gif.read_bytes(), json.loads(manifest.read_text())
            changed, first_gif, first = run()
            self.assertEqual(changed, 'true')
            changed, second_gif, second = run()
            self.assertEqual(changed, 'false')
            self.assertEqual(second_gif, first_gif)
            self.assertEqual(second['signature'], first['signature'])
            # The manifest was not rewritten: it still holds the first read time.
            self.assertEqual(second['snapshot']['observed'], first['snapshot']['observed'])
            self.assertNotIn('fetched', first)
            # One more star changes the history, so the next run re-renders.
            history['daily'][-1]['count'] += 1
            history['stars'] += 1
            changed, third_gif, third = run()
            self.assertEqual(changed, 'true')
            self.assertNotEqual(third_gif, first_gif)
            self.assertNotEqual(third['signature'], first['signature'])
            self.assertEqual(third['last_frame_stars'], 1001)


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
