"""CPU point projection: one particle per star, with no downsampling or GPU."""
import hashlib
import math
from functools import lru_cache
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .history import validate_snapshot

VERSION = '5'
GROWTH = .5          # Fraction of the clip spent growing; the rest holds the finished galaxy.
FADE_SECONDS = .6    # Crossfade to the background before the loop restarts.
MAX_TRAILS = 180
MAX_SPIKES = 45
TRAIL_SPACING = .5  # Pixels of arc between trail samples.
PROJECTION_SCALE = .43  # Screen pixels per unit of galaxy radius, per pixel of width.
TONE_STEPS = 4096   # Tone table resolution per unit of energy.
TONE_LIMIT = 8      # The tone curve is saturated (255) well below this energy.
COUNTER_MIN = 11    # The star counter stays the largest label at small widths.
TRANSPARENT = 255   # Palette index reserved for unchanged pixels.
BACKGROUND = np.array([3, 5, 12], dtype=np.float32)
TONE_CHANNELS = np.arange(3, dtype=np.float32) * (TONE_LIMIT * TONE_STEPS + 1)


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


def growth_progress(frame, frames):
    return min(1.0, frame / max(1, round((frames - 1) * GROWTH)))


def fade_frames(fps):
    return max(1, round(fps * FADE_SECONDS))


def clip_time(frame, fps):
    """Frame start time in seconds, rounded to GIF centiseconds."""
    return round(frame * 100 / fps) / 100


def utc(t, fmt):
    return datetime.fromtimestamp(t, timezone.utc).strftime(fmt)


def frame_state(data, births, end, frame, frames, fps, rotation_period):
    """Stars arrive at a constant rate; the date counter runs through quiet years quickly.

    Real star histories are hockey sticks. Advancing the clock linearly leaves the galaxy
    nearly empty for most of the clip, so the animation is linear in stars, not in time.
    Within a day bucket the stars appear in order across frames. The held frames show `end`,
    the last star day.
    """
    progress = growth_progress(frame, frames)
    count = round(data['stars'] * progress)
    when = end if progress == 1 else int(births[count - 1]) if count else data['created']
    # Match GIF centisecond timestamps, so rounded frame delays do not alter angular velocity.
    angle = 2 * math.pi * clip_time(frame, fps) / rotation_period
    return count, when, angle


def screen_positions(x, y, angle, width, height):
    """The one projection used everywhere: rotate, then a fixed tilt that reads as a galaxy.

    Returns (px, py). The rotation and tilt are folded into one affine map; a scalar angle keeps
    float32 inputs in float32, which halves the work for a million stars.
    """
    # The disk turns against the arms' winding, so the spiral arms trail as in a real galaxy.
    if np.ndim(angle):
        cosine, sine = np.cos(angle), -np.sin(angle)
    else:
        cosine, sine = math.cos(angle), -math.sin(angle)
    scale = width * PROJECTION_SCALE
    px = width * .5 + x * ((.97 * cosine + .16 * sine) * scale) + y * ((.16 * cosine - .97 * sine) * scale)
    py = height * .48 + x * ((.56 * sine - .22 * cosine) * scale) + y * ((.22 * sine + .56 * cosine) * scale)
    return px, py


def pixel_indices(px, py, width, height):
    ix, iy = np.rint(px).astype(np.intp), np.rint(py).astype(np.intp)
    if ix.size and (ix.min() < 0 or ix.max() >= width or iy.min() < 0 or iy.max() >= height):
        raise ValueError('Projection clipped a star')
    iy *= width
    iy += ix
    return iy


def project(x, y, count, angle, width, height):
    return pixel_indices(*screen_positions(x[:count], y[:count], angle, width, height), width, height)


@lru_cache(maxsize=16)
def font(size):
    # Pillow embeds Aileron, so labels render identically on every runner.
    return ImageFont.load_default(size=size)


def star_colors(x, y):
    """Warm old stars, copper transitions, and electric blue-violet outer stars."""
    radius = np.hypot(x, y)
    anchors = np.array([0, .10, .26, .40, .55, .73, .96])
    colors = np.array([[1, .88, .56], [1, .68, .24], [1, .32, .13],
                       [1, .76, .35], [.24, .50, 1], [.33, .24, 1], [.68, .26, 1]])
    return np.stack([np.interp(radius, anchors, colors[:, channel]) for channel in range(3)], axis=1).astype(np.float32)


def effect_subset(candidates, cap):
    """A fixed subset of existing stars, chosen by rank so identities never shuffle as N grows."""
    if len(candidates) > cap:
        candidates = candidates[np.linspace(0, len(candidates) - 1, cap).astype(int)]
    return candidates


def trail_stars(x, y, brightness, cap):
    return effect_subset(np.flatnonzero((brightness > 3.5) & (np.hypot(x, y) > .10)), cap)


def trail_splats(x, y, brightness, colors, eligible, count, angle, elapsed, rotation_period, width, height):
    """Light trails behind a few existing stars as (pixel indices, RGB weights), fully vectorized.

    Each trail is sampled every TRAIL_SPACING pixels of arc and every sample is splatted
    bilinearly onto its four neighbouring pixels, so a trail is a continuous anti-aliased
    line rather than a row of beads. Weights carry the projected length each sample stands
    for, so the light per pixel of arc matches a 1px line whatever the trail's length.
    Trails add light; they never add points.
    """
    eligible = eligible[:np.searchsorted(eligible, count)]
    if not len(eligible) or elapsed <= 0:
        return np.zeros(0, dtype=np.intp), np.zeros((0, 3), dtype=np.float32)
    radius = np.hypot(x[eligible], y[eligible])
    lengths = np.minimum(.40 + brightness[eligible] * .028, elapsed * 2 * math.pi / rotation_period)
    samples = np.maximum(2, np.ceil(lengths * radius * width * PROJECTION_SCALE / TRAIL_SPACING).astype(np.intp) + 1)
    owner = np.repeat(np.arange(len(eligible)), samples)
    first = np.cumsum(samples) - samples
    t = ((np.arange(len(owner)) - first[owner]) / (samples[owner] - 1)).astype(np.float32)  # 0 = head, 1 = tail
    stars = eligible[owner]
    px, py = screen_positions(x[stars], y[stars], angle - lengths[owner] * t, width, height)
    step = np.hypot(np.diff(px), np.diff(py))
    ds = np.append(step, 0)
    last = first + samples - 1
    ds[last] = ds[last - 1]
    weight = (.14 + .55 * (1 - t) ** 1.5) * .85 * ds
    x0, y0 = np.floor(px), np.floor(py)
    fx, fy = px - x0, py - y0
    ix, iy = x0.astype(np.intp), y0.astype(np.intp)
    if ix.min() < 0 or ix.max() >= width - 1 or iy.min() < 0 or iy.max() >= height - 1:
        raise ValueError('Projection clipped a trail')
    base = iy * width + ix
    indices = np.concatenate([base, base + 1, base + width, base + width + 1])
    weights = np.concatenate([weight * (1 - fx) * (1 - fy), weight * fx * (1 - fy),
                              weight * (1 - fx) * fy, weight * fx * fy])
    return indices, weights[:, None] * np.tile(colors[stars], (4, 1))


def fit_label(draw, value, size, max_width):
    """The longest prefix of value, plus an ellipsis, that fits max_width ('' if nothing does)."""
    fits = lambda text: draw.textlength(text, font=font(size)) <= max_width
    if fits(value):
        return value
    if not fits('…'):
        return ''
    # Width grows with the prefix length, so binary search for the longest prefix that fits.
    low, high = 0, len(value)  # value[:low] + '…' fits; value[:high] + '…' does not.
    while high - low > 1:
        middle = (low + high) // 2
        if fits(value[:middle] + '…'):
            low = middle
        else:
            high = middle
    return value[:low] + '…'


@lru_cache(maxsize=1)
def tone_table():
    """Tone curve and background as a lookup table; evaluating exp and pow per pixel is slow.

    Entry i covers energies [i, i + 1) / TONE_STEPS and is evaluated at the bin center (the
    first bin at exactly 0, so empty sky stays the background color). Channels are stored
    one after another, TONE_CHANNELS apart.
    """
    energy = (np.arange(TONE_LIMIT * TONE_STEPS + 1) + .5) / TONE_STEPS
    energy[0] = 0
    rgb = (1 - np.exp(-energy * 1.3)) ** .82
    return np.uint8(np.clip(BACKGROUND + rgb[:, None] * (255 - BACKGROUND), 0, 255)).T.ravel()


def blur(image, radius):
    """GaussianBlur of only the lit part of the frame; identical to blurring the whole frame."""
    box = image.getbbox()
    if box is None:
        return image
    margin = math.ceil(radius * 6) + 2
    box = (max(0, box[0] - margin), max(0, box[1] - margin),
           min(image.width, box[2] + margin), min(image.height, box[3] + margin))
    result = Image.new(image.mode, image.size)
    result.paste(image.crop(box).filter(ImageFilter.GaussianBlur(radius)), box[:2])
    return result


def enlarge(image, factor, size):
    """Bilinear upscale of a reduced frame, computed only where it is lit.

    Pillow clamps resampling to the whole source image, not the box, so this is identical to
    resizing everything; the box keeps the grid aligned with the full-resolution frame.
    """
    box = image.getbbox()
    result = Image.new(image.mode, size)
    if box is None:
        return result
    left, top = max(0, box[0] * factor - factor), max(0, box[1] * factor - factor)
    right, bottom = min(size[0], box[2] * factor + factor), min(size[1], box[3] * factor + factor)
    result.paste(image.resize((right - left, bottom - top), Image.Resampling.BILINEAR,
                              box=(left / factor, top / factor, right / factor, bottom / factor)), (left, top))
    return result


def layout(data, width, height, scale):
    """Label and timeline geometry, computed once per render in pixels.

    Positions are designed on an 800px-wide frame and scaled. Font sizes scale too but never
    drop below a legible 9 px; the star counter stays the largest label (COUNTER_MIN).
    """
    def size(design, floor=9):
        return max(floor, round(design * scale))
    def at(x, y):
        return round(x * scale), round(y * scale)
    counter = size(15, COUNTER_MIN)
    draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    counter_width = draw.textlength(f'{data["stars"]:,} STARS', font=font(counter))
    label = fit_label(draw, data['repository'], size(12), (772 - 28) * scale - counter_width - 24 * scale)
    years_y = round(height - 27 * scale)
    return {'repository': label,
            # (position, font size) per label.
            'text': {'repository': (at(28, 22), size(12)),
                     'counter': (at(772, 20), counter),
                     # The date sits below the counter, whose floor size can exceed its scaled size.
                     'date': ((round(772 * scale), round(20 * scale + counter + 7 * scale)), size(10)),
                     'empty': (at(400, 240), size(13)),
                     'start_year': ((round(152 * scale), years_y), size(9)),
                     'end_year': ((round(648 * scale), years_y), size(9))},
            'timeline': {'y': int(height - 38 * scale), 'left': int(width * .19), 'right': int(width * .81),
                         'stroke': max(1, round(2 * scale)), 'knob': max(2, round(3 * scale))}}


def prepare(data, particle_data, width, height):
    """Per-render constants, so frames do not recompute per-particle products or effect subsets."""
    x, y, brightness, _ = particle_data
    colors = star_colors(x, y)
    scale = width / 800
    # All N stars contribute. Fixed exposure preserves growth through the whole clip. Stars start
    # to share pixels at ~6,500 on an 800px frame; the knee scales with pixel area, so a narrow
    # GIF of a big repository is not overexposed.
    exposure = max(1, data['stars'] / (6500 * scale ** 2)) ** .78
    weights = np.ascontiguousarray((brightness[:, None] * colors).T, dtype=np.float64) / exposure
    spikes = effect_subset(np.flatnonzero(brightness > 6.6), min(MAX_SPIKES, data['stars'] // 150))
    # The clip ends on the last star day, not the fetch time, so it does not change from day to day.
    end = max(data['created'], max((d['time'] for d in data['daily']), default=0))
    return {'colors': colors, 'weights': weights, 'trails': trail_stars(x, y, brightness, min(MAX_TRAILS, data['stars'] // 40)),
            'spikes': spikes, 'spike_colors': [tuple((np.minimum(1, colors[i] * .6 + .4) * 255).astype(int)) for i in spikes],
            'end': end, 'layout': layout(data, width, height, scale)}


def render_frame(data, particle_data, scene, frame, frames, fps, rotation_period, width, height):
    x, y, brightness, births = particle_data
    colors = scene['colors']
    count, when, angle = frame_state(data, births, scene['end'], frame, frames, fps, rotation_period)
    indices = project(x, y, count, angle, width, height)
    energy = np.empty((height * width, 3), dtype=np.float32)
    for c in range(3):
        energy[:, c] = np.bincount(indices, weights=scene['weights'][c, :count], minlength=width * height)
    elapsed = clip_time(frame, fps)
    trail_indices, trail_weights = trail_splats(x, y, brightness, colors, scene['trails'], count, angle, elapsed,
                                                rotation_period, width, height)
    if len(trail_indices):
        for c in range(3):
            energy[:, c] += np.bincount(trail_indices, weights=trail_weights[:, c], minlength=width * height)
    energy = energy.reshape(height, width, 3)
    # Two bloom scales and a broad nebular haze, derived only from particle light. The wide
    # blurs run at half and quarter resolution; they are smooth enough that this is invisible.
    buffer = np.multiply(energy, 100)
    np.minimum(buffer, 255, out=buffer)
    source = Image.fromarray(buffer.astype(np.uint8), 'RGB')
    glow = np.asarray(blur(source, width / 600))
    halo = np.asarray(enlarge(blur(source.reduce(2), width / 320), 2, source.size))
    haze = np.asarray(enlarge(blur(source.reduce(4), width / 180), 4, source.size))
    # energy * 1.5 + glow * 2.1 + halo * 1.5 + haze * .8, with the blurs stored at 100x.
    bloom = np.multiply(glow, 21, dtype=np.uint16)
    bloom += np.multiply(halo, 15, dtype=np.uint16)
    bloom += np.multiply(haze, 8, dtype=np.uint16)
    total = np.multiply(energy, 1.5 * TONE_STEPS, out=buffer)
    total += bloom * np.float32(TONE_STEPS / 1000)
    np.minimum(total, TONE_LIMIT * TONE_STEPS, out=total)
    total += TONE_CHANNELS
    lookup = total.astype(np.intp)
    image = Image.fromarray(tone_table()[lookup], 'RGB')
    draw = ImageDraw.Draw(image)
    # Small diffraction spikes belong to particularly luminous existing points.
    shown = int(np.searchsorted(scene['spikes'], count))
    px, py = screen_positions(x[scene['spikes'][:shown]], y[scene['spikes'][:shown]], angle, width, height)
    r = max(1, round(width / 500))
    for sx, sy, color in zip(px.tolist(), py.tolist(), scene['spike_colors']):
        draw.line((sx-r, sy, sx+r, sy), fill=color)
        draw.line((sx, sy-r, sx, sy+r), fill=color)
        draw.point((sx, sy), fill=(255, 252, 239))
    labels = scene['layout']
    def text(key, value, fill=(167, 176, 195), anchor=None):
        xy, size = labels['text'][key]
        draw.text(xy, value, font=font(size), fill=fill, anchor=anchor)
    text('repository', labels['repository'])
    text('counter', f'{count:,} STARS', (235, 227, 207), 'ra')
    text('date', utc(when, '%Y-%m-%d'), anchor='ra')
    if not data['stars']:
        text('empty', 'A galaxy begins with its first star.', anchor='mm')
    # A restrained timeline leaves the galaxy as the focal point.
    line = labels['timeline']
    line_y, left, right, r = line['y'], line['left'], line['right'], line['knob']
    cursor = round(left + (right - left) * growth_progress(frame, frames))
    draw.line((left, line_y, right, line_y), fill=(42, 45, 59), width=line['stroke'])
    draw.line((left, line_y, cursor, line_y), fill=(168, 158, 166), width=line['stroke'])
    draw.ellipse((cursor-r, line_y-r, cursor+r, line_y+r), fill=(231, 215, 187))
    # The end label is the year of the final frame's date (the last star day), not the render
    # date, so it is honest for quiet repositories and the GIF does not change from day to day.
    text('start_year', utc(data['created'], '%Y'))
    text('end_year', utc(scene['end'], '%Y'), anchor='ra')
    # Soften the loop: fade to the background so the restart is not a hard cut.
    fading = fade_frames(fps)
    remaining = frames - 1 - frame
    if remaining < fading:
        alpha = (fading - remaining) / (fading + 1)
        image = Image.blend(image, Image.new('RGB', image.size, tuple(BACKGROUND.astype(int))), alpha)
    return image, count


def gif_palette(images):
    """One palette sampled across the clip avoids frame-to-frame color pumping.

    The samples are tiled at full resolution: downscaling first averages away the single-pixel
    stars and thin trails, which then land on wrong hues. Fast octree spreads the colors over
    the bright galaxy instead of spending most of them on near-black haze, which is both more
    faithful and far cheaper to LZW-compress. One index stays free for frame-diff transparency.
    """
    width, height = images[0].size
    columns = 4
    atlas = Image.new('RGB', (width * columns, height * math.ceil(len(images) / columns)))
    for i, image in enumerate(images):
        atlas.paste(image, ((i % columns) * width, (i // columns) * height))
    return atlas.quantize(colors=TRANSPARENT, method=Image.Quantize.FASTOCTREE)


def render_gif(data, output, width=800, fps=10, duration=10, rotation_period=30):
    if type(width) is not int or not 400 <= width <= 1200:
        raise ValueError('width must be an integer from 400 to 1200')
    if type(fps) is not int or not 5 <= fps <= 25:
        raise ValueError('fps must be an integer from 5 to 25')
    if not 4 <= duration <= 30 or not 5 <= rotation_period <= 120:
        raise ValueError('duration must be 4–30 and rotation-period must be 5–120 seconds')
    height = round(width * 530 / 800)
    frames = round(fps * duration)
    particle_data = particles(data)
    scene = prepare(data, particle_data, width, height)
    def render(frame):
        return render_frame(data, particle_data, scene, frame, frames, fps, rotation_period, width, height)
    # The palette is built from a dozen sample frames (held in full color, plus a full-resolution
    # atlas of them); the remaining frames are quantized one at a time as they are rendered.
    # One sample sits mid-fade: dimmed core colors appear nowhere else in the clip.
    fade_middle = frames - 1 - fade_frames(fps) // 2
    sample_frames = sorted(set(np.linspace(0, frames - 1, 11).astype(int).tolist() + [fade_middle]))
    rendered = {f: render(f) for f in sample_frames}
    palette = gif_palette([rendered[f][0] for f in sample_frames])
    colors = palette.getpalette()
    images, counts, shown = [], [], None
    for frame in range(frames):
        image, count = rendered.pop(frame, None) or render(frame)
        indices = np.asarray(image.quantize(palette=palette, dither=Image.Dither.NONE))
        if indices.max() >= TRANSPARENT:
            raise RuntimeError('GIF quantization used the palette index reserved for transparency')
        # Exact frame differencing: pixels whose palette index is unchanged become transparent
        # and the previous frame shows through (disposal 1). Decoded frames are identical to the
        # quantized frames; the rotating galaxy just compresses much better this way.
        delta = indices if shown is None else np.where(indices == shown, np.uint8(TRANSPARENT), indices)
        shown = indices
        encoded = Image.fromarray(delta, 'P')
        encoded.putpalette(colors)
        images.append(encoded)
        counts.append(count)
    # GIF delays use centiseconds. Distribute rounding to preserve overall timing.
    delays = [round((clip_time(i + 1, fps) - clip_time(i, fps)) * 1000) for i in range(frames)]
    if counts[0] != 0 or counts[-1] != data['stars']:
        raise RuntimeError(f'Rendered {counts[0]:,} stars in the first frame and {counts[-1]:,} in the last; '
                           f'expected 0 and {data["stars"]:,}')
    images[0].save(output, save_all=True, append_images=images[1:], duration=delays,
                   loop=0, optimize=False, disposal=1, transparency=TRANSPARENT)
    return {'particles': len(particle_data[0]), 'first_frame_stars': counts[0], 'last_frame_stars': counts[-1],
            'frame_counts': counts, 'frames': frames, 'width': width, 'height': height,
            'rotation_period': rotation_period, 'fps': fps}
