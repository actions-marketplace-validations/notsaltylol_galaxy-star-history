# Galaxy Star History

Turn a repository's GitHub star history into an animated galaxy in its README.
Every GitHub star becomes **one point**. The animation starts at zero, adds points
according to GitHub's daily history, reaches the current star count, and holds the
completed galaxy before replaying. Rotation speed stays constant throughout.

**GIF output. No SVG, GPU, browser, hosted API, or external rendering service.**
The visual uses a golden nucleus, blue-violet outer stars, curved light trails,
and bloom derived from the stars themselves. The action runs on a standard Ubuntu runner and supports up to **1,000,000 stars**
without sampling. This repository is a Marketplace-ready scaffold; no Marketplace
release or `v1` tag has been published yet.

## Use the action

Once a release is published, pin it to a reviewed commit SHA or use its version tag:

```yaml
- uses: actions/checkout@v4
- uses: notsaltylol/galaxy-star-history@v1
  id: galaxy
  with:
    repository: ${{ github.repository }}
    token: ${{ github.token }}
    output: galaxy.gif
```

The action generates `galaxy.gif` and `galaxy.json`. It does **not** commit or push
anything itself. The JSON manifest records the source snapshot, exact particle
count, every frame's count, and the image checksum for auditing.

For this repository, [the included workflow](.github/workflows/galaxy.yml) uses the
local action, runs daily or manually, and publishes the image and manifest to an
`assets` branch. In another repository, copy that workflow and replace `uses: ./`
with `uses: notsaltylol/galaxy-star-history@v1` after the release exists. Keep
`contents: write` for the publishing step; the generation step needs only metadata
read access. No custom PAT is required for a public repository on GitHub.com.

After the first successful publishing run, put this in your README, replacing
`OWNER/REPO` with the repository **where the workflow runs**:

```markdown
![Animated galaxy of repository stars](https://raw.githubusercontent.com/OWNER/REPO/assets/galaxy.gif)
```

GitHub serves the file. The GIF plays immediately in the README; the underlying
data changes on the workflow schedule. GitHub's image cache may delay refreshes.
Scheduled runs are best-effort and GitHub may disable schedules in inactive public
repositories. Use **Actions → Update star galaxy → Run workflow** to refresh manually.

## Accuracy contract

- **No sampling, representative particles, count scaling, or decorative stars.**
  N current GitHub stars means N stored particles and N point contributions in the
  final frame. Zero-star repositories stay empty.
- All pages of GitHub's `/repos/{owner}/{repo}/stargazers/history` endpoint are read.
  The action compares their summed daily counts with `/stargazers/count`.
- If the totals disagree, it retries the snapshot once and then **fails without
  replacing the existing GIF**. It never silently drops or invents stars.
- Births follow the API's daily buckets. Many stars may appear in one frame; the
  daily API does not supply an individual timestamp or identity for each star.
  This is a replay of the available history, not a claim to reconstruct unstars
  or exact historical net totals.
- All stars rotate together at a fixed angular velocity. The history clock and
  rotation clock are independent. Growth occupies the first 80% of the clip;
  the final count holds for the remainder while rotation continues.
- The final-to-first loop deliberately resets the galaxy to zero. It is not a
  seamless physical orbit loop.
- Points can overlap on the same pixel at README resolution. Every point still
  contributes to brightness; one million points cannot all be separately resolved
  in an 800-pixel-wide image. The on-image counter and JSON manifest expose the
  exact count. Bloom is derived solely from actual particles. Trails and diffraction spikes
  decorate a fixed subset of existing stars (at most 180 trails and 45 spikes);
  those limits never reduce the number of star points.
- More than one million stars is an explicit error, never an implicit cap.

[GitHub history API documentation](https://docs.github.com/en/rest/activity/starring#get-repository-star-history)

## Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `repository` | `${{ github.repository }}` | Public GitHub.com repository, `owner/repo` |
| `token` | `${{ github.token }}` | Token permitted to read target repository metadata |
| `output` | `galaxy.gif` | Relative workspace GIF path; matching `.json` is also written |
| `width` | `800` | Image width, 400–1200 pixels |
| `fps` | `15` | 5–25 frames per second |
| `duration` | `10` | 4–30 seconds, including final hold |
| `rotation-period` | `30` | 5–120 seconds per full rotation |

Outputs: `path`, `manifest`, `changed` (`true`/`false`), and `stars`.
The renderer is CPU-only, using NumPy for point projection and Pillow for GIF
encoding. Runtime and memory increase with frame count, resolution, and stars.
Start with defaults; the CI workflow renders a full million-star fixture and
uploads the benchmark GIF and count report. A render is skipped when the existing
GIF, manifest, source data, and options match within the same UTC day.

Supported action environment: **Linux runners with Bash and Python setup support**.
GitHub Enterprise Server is not supported in this initial version. For private
repositories, explicitly ensure the publishing destination is appropriate for the
repository data; the default `GITHUB_TOKEN` only covers its own repository.

## Development

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s test -v
.venv/bin/python examples/generate.py --stars 1000000 --output /tmp/million.gif
```

For real data, set `INPUT_REPOSITORY=owner/repo` and `INPUT_TOKEN` in the environment,
then run `.venv/bin/python -m galaxy`. Never put the token in source or the README.
Fixtures are labeled `example/synthetic-galaxy`; they are not actual repository data.

## Publish to Marketplace

1. Push this scaffold to the public repository and let CI pass on Ubuntu.
2. Run **Update star galaxy** and inspect the README GIF and accuracy manifest.
3. Review the action name's availability and the repository's license and metadata.
4. Create the first release (for example `v1.0.0`) and a corresponding `v1` tag.
5. In GitHub's release UI select **Publish this Action to the GitHub Marketplace**,
   choose the categories, and accept GitHub's Marketplace terms if prompted.

The repository includes root `action.yml`, branding, MIT license, usage docs,
unit tests, scheduled publication, and CI. Publishing a GitHub release is separate
from scaffolding the action; this scaffold does not automatically publish releases.
See [GitHub's publishing guide](https://docs.github.com/en/actions/how-tos/create-and-publish-actions/publish-in-github-marketplace).

## License

MIT. See [LICENSE](LICENSE).
