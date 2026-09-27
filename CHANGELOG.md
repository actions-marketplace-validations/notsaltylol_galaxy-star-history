# Changelog

## Unreleased

- Composite GitHub Action that renders a repository's star history as an animated galaxy GIF on a CPU-only Ubuntu runner (NumPy + Pillow).
- One point per current star, from zero to one million stars, with no sampling or scaling.
- Warm nucleus, cool outer disk, curved trails, and bloom derived from the stars themselves.
- Reads all pages of the star-history API, checks the total against the current count, retries once, and fails without replacing the GIF on mismatch.
- JSON manifest with the snapshot, per-frame star counts, and GIF checksum; outputs `path`, `manifest`, `changed`, and `stars`.
- Included workflow publishes the GIF and manifest to an `assets` branch daily or on demand; CI renders a million-star fixture.
- Growth is linear in star count rather than calendar time; stars within a day bucket appear in order across frames.
- The current count is reached halfway through; the finished galaxy then holds, and the last 0.6 s fade to black before the loop.
- Trails and diffraction spikes scale with star count (at most `min(180, stars // 40)` and `min(45, stars // 150)`).
- Render signature excludes the time of the API read, so the GIF is byte-identical and nothing is published until the star history changes; the manifest's `snapshot.observed` is the UTC time of the API read, while the final frame's date and the timeline's right-hand label are the last star day.
- The `assets` branch is a single force-pushed commit, so repository history does not accumulate GIFs.
- Labels use Pillow's embedded Aileron font for runner-independent output; long repository names are truncated with an ellipsis.
- Trails are rendered with vectorized NumPy instead of per-star loops.
- A single projection function is shared by stars, trails, and spikes.
- The shared GIF palette is built from a dozen sample frames; the remaining frames are quantized one at a time as they are rendered, so memory does not grow with clip length.
- Default `fps` is 10 (was 15), which cuts real-repository GIFs by about a third (for example 11.3 MB to 7.7 MB at 9.5k stars, 14.6 MB to 9.7 MB at 250k stars).
- The timeline's right-hand label is the year of the most recent star (the finished galaxy's date) instead of `NOW`.
- Internal consistency failures during rendering are reported as `Galaxy generation failed: ...` rather than a traceback, and are not skipped under `python -O`.
