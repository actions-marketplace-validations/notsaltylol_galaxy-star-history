# Galaxy Star History

Your repository's stars, drawn as a galaxy in your README.

Every point of light is one real person who starred the repo. If you starred it, you are in
there. The galaxy starts empty, fills as people arrive, then holds and slowly turns.

It runs in your own GitHub Actions: no third-party service, no GPU, no browser. A plain
Ubuntu runner renders a GIF with NumPy and Pillow, and GitHub serves the file.

This is a Marketplace-ready scaffold; no release or `v1` tag exists yet.

## Examples

Real renders from the GitHub star-history API at default settings, published on the
[`examples` branch](https://github.com/notsaltylol/galaxy-star-history/tree/examples).

![star-history/star-history, 9,537 stars, as a galaxy](https://raw.githubusercontent.com/notsaltylol/galaxy-star-history/examples/star-history.gif)

star-history/star-history: 9,537 stars, rendered 2026-09-26 at defaults.

![facebook/react, 250,764 stars, as a galaxy](https://raw.githubusercontent.com/notsaltylol/galaxy-star-history/examples/react.gif)

facebook/react: 250,764 stars, rendered 2026-09-26 at defaults.

## Use the action

Pin a reviewed commit SHA, or the release tag once published:

```yaml
- uses: actions/checkout@v4
- uses: notsaltylol/galaxy-star-history@v1
  id: galaxy
  with:
    repository: ${{ github.repository }}
    token: ${{ github.token }}
    output: galaxy.gif
```

The action writes `galaxy.gif` and a `galaxy.json` manifest. It does not commit or push.

[The included workflow](.github/workflows/galaxy.yml) runs daily and on demand and publishes
both files to an `assets` branch. To reuse it, copy it and replace `uses: ./` with
`uses: notsaltylol/galaxy-star-history@v1`. The publish step needs `contents: write`; a
public GitHub.com repository needs no personal access token.

After the first publish, add this to your README, with `OWNER/REPO` set to the repository
where the workflow runs:

```markdown
![Animated galaxy of repository stars](https://raw.githubusercontent.com/OWNER/REPO/assets/galaxy.gif)
```

Scheduled runs are best-effort, and GitHub may disable schedules in inactive public
repositories. Use **Actions > Update star galaxy > Run workflow** to refresh by hand.

## What you see

- **Growth follows stars, not the calendar.** The first frame is empty. Stars arrive at a
  steady rate and reach the current count halfway through. The date counter races through
  quiet years and slows during bursts.
- **Hold and fade.** The finished galaxy holds and rotates for the second half. The last
  0.6 seconds fade to black, so the loop restart is not a hard cut. The very last frames
  are that fade, so the finished galaxy is best seen mid-loop.
- **Constant rotation**, set by `rotation-period` and independent of growth.
- **Timeline.** The bar under the galaxy runs from the year the repository was created to the
  year of its most recent star, which is also the date shown on the finished galaxy.
- **Trails and diffraction spikes** highlight a fixed subset of existing stars: at most
  one trail per 40 stars, up to 180, and one spike per 150 stars, up to 45. They never add
  points.
- **Labels** use Pillow's embedded Aileron font, so output is identical on any runner. Long
  `owner/repo` names end in an ellipsis.

## Updates and cost

The GIF and its signature depend only on the star history and the inputs, not on when the
API was read, so the GIF stays byte-identical until someone stars or unstars the repo. A
renderer upgrade (a new action version) also re-renders it. On unchanged days `changed` is
`false` and nothing is published.

When it does publish, the included workflow replaces the `assets` branch with a single
commit and force-pushes it, so your history does not collect a multi-megabyte GIF per
update. If you pinned an `assets` commit SHA, expect it to be rewritten.

The GIF is large, because the whole galaxy moves in every frame, and it is downloaded on
every README view. At defaults (800 px, 10 fps, 10 s) real repositories measure about 7.5–10 MB:
about 8 MB for a 10,000-star repository and about 10 MB for a 250,000-star one. Size scales
roughly with pixel area and frame count, so `width: 600` cuts it by about 40%, and a lower
`fps` or a shorter `duration` shrinks it in proportion (`duration: 6` is about 4.5–6 MB).

## Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `repository` | `${{ github.repository }}` | Public GitHub.com repository, `owner/repo` |
| `token` | `${{ github.token }}` | Token permitted to read target repository metadata |
| `output` | `galaxy.gif` | Relative workspace GIF path; matching `.json` is also written |
| `width` | `800` | Image width, 400–1200 pixels |
| `fps` | `10` | 5–25 frames per second |
| `duration` | `10` | 4–30 seconds, including final hold |
| `rotation-period` | `30` | 5–120 seconds per full rotation |

Outputs: `path`, `manifest`, `changed` (`true`/`false`), and `stars`.

Linux runners only; GitHub Enterprise Server is not supported. For private repositories,
check that the publishing destination is appropriate for the data.

## What is exact, and what is art

The counts are exact. The positions are decorative.

- **Counts.** N stars on GitHub means N points in the final frame. No sampling, no scaling.
- **Positions** encode only arrival order: older stars sit in the nucleus, newer ones in the
  outer disk. The arms, clusters, and halo are synthetic. A point does not identify a person.
- **Timing.** GitHub reports stars per day, not per person, so stars from one day appear in
  history order across frames. Unstars are not replayed.
- **Source.** The action reads every page of `/repos/{owner}/{repo}/stargazers/history`
  (weekly buckets with per-day counts) and `/repos/{owner}/{repo}/stargazers/count`. If the
  totals disagree it retries once, then fails without replacing the existing GIF.
  [API docs](https://docs.github.com/en/rest/activity/starring#get-repository-star-history).
- **Manifest.** `galaxy.json` records the snapshot, per-frame star counts, the GIF checksum,
  and the render signature. `snapshot.observed` is the UTC time of the API read; the signature
  excludes it. The final frame's date and the timeline's right-hand label are the last star day.
- **Limit.** Up to 1,000,000 stars. Beyond that the action fails rather than sample.

## Development

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s test -v
.venv/bin/python examples/generate.py --stars 1000000 --output /tmp/million.gif
```

For real data, set `INPUT_REPOSITORY=owner/repo` and `INPUT_TOKEN`, then run
`.venv/bin/python -m galaxy`. Never commit the token. Fixtures use the name
`example/synthetic-galaxy` and are not real data.

## Publish to Marketplace

1. Push to the public repository and let CI pass.
2. Run **Update star galaxy** and check the GIF and manifest.
3. Create a release (for example `v1.0.0`) and a matching `v1` tag, choosing
   **Publish this Action to the GitHub Marketplace**.

See [GitHub's publishing guide](https://docs.github.com/en/actions/how-tos/create-and-publish-actions/publish-in-github-marketplace).

## License

MIT. See [LICENSE](LICENSE).
