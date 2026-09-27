"""CPU point projection: one particle per star, with no downsampling or GPU."""
import hashlib
import math
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .history import validate_snapshot

VERSION = '3'


def particles(data):
    validate_snapshot(data)
    n = data['stars']
    seed = int.from_bytes(hashlib.sha256(data['repository'].encode()).digest()[:8], 'little')
    # Interleaved random attributes preserve each point's random identity as N grows.
    noise = np.random.default_rng(seed).random((n, 4), dtype=np.float32)
    indices = np.arange(n, dtype=np.float32)
    # Concentrate older stars in a luminous nucleus; broaden newer outer orbits.
    rank = (indices + .5) / max(n, 1)
    radius = rank ** 1.45
    arm = np.arange(n, dtype=np.int32) % 2
    macro = .17 * np.sin(radius * 9 + arm * 2.1)
    clusters = .09 * np.sin(radius * 43 + arm)
    angle = arm * math.pi + 5.2 * np.log1p(radius * 9) + macro + clusters
    angle += (noise[:, 0] - .5) * (1.0 + radius * 1.1)
    # Existing stars form a faint diffuse population between the spiral arms.
    angle = np.where(noise[:, 3] < .22, noise[:, 0] * 2 * math.pi, angle)
    radius = np.clip(radius * .91 + (noise[:, 1] - .5) * (.012 + radius * .08), .001, .96)
    x = (radius * np.cos(angle)).astype(np.float32)
    y = (radius * np.sin(angle)).astype(np.float32)
    brightness = (.4 + noise[:, 2] ** 9 * 7).astype(np.float32)
    births = np.repeat(np.array([d['time'] for d in data['daily']], dtype=np.int64),
                       np.array([d['count'] for d in data['daily']], dtype=np.int64))
    assert len(x) == len(y) == len(brightness) == len(births) == n
    return x, y, brightness, births


def frame_state(data, births, frame, frames, fps, rotation_period):
    # The first frame is genuinely empty. Reach today's count at 80%, then hold.
    progress = min(1.0, frame / max(1, int((frames - 1) * .8)))
    earliest = min(data['created'], int(births[0]) if len(births) else data['created'])
    when = int(earliest + (data['observed'] - earliest) * progress)
    count = 0 if frame == 0 else int(np.searchsorted(births, when, side='right'))
    if progress == 1:
        count = data['stars']
    # Match GIF centisecond timestamps, so rounded frame delays do not alter angular velocity.
    elapsed = round(frame * 100 / fps) / 100
    angle = 2 * math.pi * elapsed / rotation_period
    return count, when, angle


def project(x, y, count, angle, width, height):
    cosine, sine = math.cos(angle), math.sin(angle)
    rx = x[:count] * cosine - y[:count] * sine
    ry = x[:count] * sine + y[:count] * cosine
    # Fixed tilt makes the planar swirl read as a galaxy; all points stay in frame.
    px = width * .5 + (rx * .97 + ry * .16) * width * .43
    py = height * .48 + (-rx * .22 + ry * .56) * width * .43
    ix, iy = np.rint(px).astype(np.int32), np.rint(py).astype(np.int32)
    if count and (ix.min() < 0 or ix.max() >= width or iy.min() < 0 or iy.max() >= height):
        raise ValueError('Projection clipped a star')
    return iy * width + ix


@lru_cache(maxsize=16)
def font(size):
    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
                 '/System/Library/Fonts/Menlo.ttc'):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def star_colors(x, y):
    """Warm old stars, copper transitions, and electric blue-violet outer stars."""
    radius = np.hypot(x, y)
    anchors = np.array([0, .10, .26, .40, .55, .73, .96])
    colors = np.array([[1, .88, .56], [1, .68, .24], [1, .32, .13],
                       [1, .76, .35], [.24, .50, 1], [.33, .24, 1], [.68, .26, 1]])
    return np.stack([np.interp(radius, anchors, colors[:, channel]) for channel in range(3)], axis=1).astype(np.float32)


def screen_positions(x, y, angle, width, height):
    cosine, sine = math.cos(angle), math.sin(angle)
    rx, ry = x * cosine - y * sine, x * sine + y * cosine
    return np.stack([width * .5 + (rx * .97 + ry * .16) * width * .43,
                     height * .48 + (-rx * .22 + ry * .56) * width * .43], axis=-1)


def trail_layer(x, y, brightness, colors, count, angle, elapsed, rotation_period, width, height):
    """Continuous light trails of existing stars; never additional point sprites."""
    layer = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(layer)
    # Limit only optical effects, not stars. Every star is rasterized below.
    eligible = np.flatnonzero((brightness > 3.5) & (np.hypot(x, y) > .10))
    if len(eligible) > 180:
        eligible = eligible[np.linspace(0, len(eligible) - 1, 180).astype(int)]
    eligible = eligible[eligible < count]
    for i in eligible:
        length = min(.40 + brightness[i] * .028, elapsed * 2 * math.pi / rotation_period)
        if length <= 0:
            continue
        offsets = np.linspace(length, 0, 17)
        points = np.array([screen_positions(x[i], y[i], angle - offset, width, height) for offset in offsets])
        for j in range(16):
            intensity = .14 + .55 * (j / 16) ** 1.5
            color = tuple((colors[i] * intensity * 255).astype(int))
            draw.line([tuple(points[j]), tuple(points[j + 1])], fill=color, width=1)
    return np.asarray(layer, dtype=np.float32) / 255


def render_frame(data, particle_data, frame, frames, fps, rotation_period, width, height, colors=None):
    x, y, brightness, births = particle_data
    count, when, angle = frame_state(data, births, frame, frames, fps, rotation_period)
    indices = project(x, y, count, angle, width, height)
    if colors is None:
        colors = star_colors(x, y)
    # All N stars contribute. Fixed exposure preserves growth through the whole clip.
    exposure = max(1, data['stars'] / 6500) ** .78
    channels = [np.bincount(indices, weights=brightness[:count] * colors[:count, c],
                           minlength=width * height).reshape(height, width) for c in range(3)]
    energy = np.stack(channels, axis=-1).astype(np.float32) / exposure
    elapsed = round(frame * 100 / fps) / 100
    energy += trail_layer(x, y, brightness, colors, count, angle, elapsed, rotation_period, width, height) * .85
    # Two bloom scales and a broad nebular haze, derived only from particle light.
    source = Image.fromarray(np.uint8(np.clip(energy * 100, 0, 255)), 'RGB')
    glow = np.asarray(source.filter(ImageFilter.GaussianBlur(width / 600)), dtype=np.float32) / 100
    halo = np.asarray(source.filter(ImageFilter.GaussianBlur(width / 160)), dtype=np.float32) / 100
    haze = np.asarray(source.filter(ImageFilter.GaussianBlur(width / 45)), dtype=np.float32) / 100
    energy = energy * 1.5 + glow * 2.1 + halo * 1.5 + haze * .8
    rgb = (1 - np.exp(-energy * 1.3)) ** .82
    background = np.array([3, 5, 12], dtype=np.float32)
    image = Image.fromarray(np.uint8(np.clip(background + rgb * (255 - background), 0, 255)), 'RGB')
    draw = ImageDraw.Draw(image)
    # Small diffraction spikes belong to particularly luminous existing points.
    highlights = np.flatnonzero(brightness > 6.6)
    if len(highlights) > 45:
        highlights = highlights[np.linspace(0, len(highlights) - 1, 45).astype(int)]
    highlights = highlights[highlights < count]
    positions = screen_positions(x[highlights], y[highlights], angle, width, height)
    for i, (px, py) in zip(highlights, positions):
        r = max(1, round(width / 500))
        color = tuple((np.minimum(1, colors[i] * .6 + .4) * 255).astype(int))
        draw.line((px-r, py, px+r, py), fill=color)
        draw.line((px, py-r, px, py+r), fill=color)
        draw.point((px, py), fill=(255, 252, 239))
    scale = width / 800
    def text(x, y, value, size=12, fill=(167, 176, 195), anchor=None):
        draw.text((round(x * scale), round(y * scale)), value, font=font(max(9, round(size * scale))), fill=fill, anchor=anchor)
    text(28, 22, data['repository'], 12)
    text(772, 20, f'{count:,} STARS', 15, (235, 227, 207), 'ra')
    text(772, 42, datetime.fromtimestamp(when, timezone.utc).strftime('%Y-%m-%d'), 10, anchor='ra')
    if not data['stars']:
        text(400, 240, 'A galaxy begins with its first star.', 13, anchor='mm')
    # A restrained timeline leaves the galaxy as the focal point.
    line_y = int(height - 38 * scale)
    left, right = int(width * .19), int(width * .81)
    progress = min(1, frame / max(1, int((frames - 1) * .8)))
    cursor = round(left + (right - left) * progress)
    draw.line((left, line_y, right, line_y), fill=(42, 45, 59), width=max(1, round(2 * scale)))
    draw.line((left, line_y, cursor, line_y), fill=(168, 158, 166), width=max(1, round(2 * scale)))
    r = max(2, round(3 * scale))
    draw.ellipse((cursor-r, line_y-r, cursor+r, line_y+r), fill=(231, 215, 187))
    start_year = datetime.fromtimestamp(data['created'], timezone.utc).strftime('%Y')
    text(152, height / scale - 27, start_year, 9)
    text(648, height / scale - 27, 'NOW', 9, anchor='ra')
    return image, count


def gif_palette(images):
    """One palette sampled across the clip avoids frame-to-frame color pumping."""
    samples = [images[i].resize((200, 132)) for i in np.linspace(0, len(images)-1, 12).astype(int)]
    atlas = Image.new('RGB', (200 * 4, 132 * 3))
    for i, sample in enumerate(samples):
        atlas.paste(sample, ((i % 4) * 200, (i // 4) * 132))
    return atlas.quantize(colors=256, method=Image.Quantize.MEDIANCUT)


def render_gif(data, output, width=800, fps=15, duration=10, rotation_period=30):
    if type(width) is not int or not 400 <= width <= 1200:
        raise ValueError('width must be an integer from 400 to 1200')
    if type(fps) is not int or not 5 <= fps <= 25:
        raise ValueError('fps must be an integer from 5 to 25')
    if not 4 <= duration <= 30 or not 5 <= rotation_period <= 120:
        raise ValueError('duration must be 4–30 and rotation-period must be 5–120 seconds')
    height = round(width * 530 / 800)
    frames = round(fps * duration)
    particle_data = particles(data)
    colors = star_colors(particle_data[0], particle_data[1])
    images, counts = [], []
    for frame in range(frames):
        image, count = render_frame(data, particle_data, frame, frames, fps, rotation_period, width, height, colors)
        images.append(image)
        counts.append(count)
    # GIF delays use centiseconds. Distribute rounding to preserve overall timing.
    delays = [(round((i + 1) * 100 / fps) - round(i * 100 / fps)) * 10 for i in range(frames)]
    palette = gif_palette(images)
    images = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in images]
    images[0].save(output, save_all=True, append_images=images[1:], duration=delays,
                   loop=0, optimize=False, disposal=2)
    assert counts[0] == 0 and counts[-1] == data['stars']
    return {'particles': len(particle_data[0]), 'first_frame_stars': counts[0], 'last_frame_stars': counts[-1],
            'frame_counts': counts, 'frames': frames, 'width': width, 'height': height,
            'rotation_period': rotation_period, 'fps': fps}
