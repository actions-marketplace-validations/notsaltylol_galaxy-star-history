import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from .history import fetch_snapshot
from .render import VERSION, render_gif


def main():
    repository = os.environ.get('INPUT_REPOSITORY') or os.environ.get('GITHUB_REPOSITORY', '')
    root = Path(os.environ.get('GITHUB_WORKSPACE', os.getcwd())).resolve()
    output = os.environ.get('INPUT_OUTPUT', 'galaxy.gif')
    relative = Path(output)
    path = (root / relative).resolve()
    if relative.is_absolute() or path == root or root not in path.parents or '.git' in path.relative_to(root).parts or path.suffix != '.gif' or '\n' in output or '\r' in output:
        raise ValueError('output must be a .gif path inside the workspace and outside .git')
    options = {'width': int(os.environ.get('INPUT_WIDTH', '800')),
               'fps': int(os.environ.get('INPUT_FPS', '10')),
               'duration': float(os.environ.get('INPUT_DURATION', '10')),
               'rotation_period': float(os.environ.get('INPUT_ROTATION_PERIOD', '30'))}
    data = fetch_snapshot(repository, os.environ.get('INPUT_TOKEN', ''))
    # The rendered clip depends only on the star history, not on when it was read, so the
    # signature (and the GIF) stays byte-identical from day to day until a star is added or removed.
    history = {key: data[key] for key in ('repository', 'created', 'stars', 'daily')}
    signature = hashlib.sha256(json.dumps([VERSION, history, options], sort_keys=True).encode()).hexdigest()
    manifest_path = path.with_suffix('.json')
    old = {}
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
    unchanged = (path.exists() and old.get('signature') == signature
                 and old.get('gif_sha256') == hashlib.sha256(path.read_bytes()).hexdigest())
    if not unchanged:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix='.gif', dir=path.parent, delete=False) as temp:
            temporary = Path(temp.name)
        try:
            report = render_gif(data, temporary, **options)
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        manifest_path.write_text(json.dumps({'signature': signature, 'gif_sha256': digest,
            'repository': repository, 'current_stars': data['stars'], 'snapshot': data, **report}, indent=2) + '\n')
    changed = str(not unchanged).lower()
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as handle:
            handle.write(f'path={output}\nmanifest={relative.with_suffix(".json")}\nchanged={changed}\nstars={data["stars"]}\n')
    print(f'{"Unchanged" if unchanged else "Generated"} {output}: exactly {data["stars"]:,} particles')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        print(f'Galaxy generation failed: {error}', file=sys.stderr)
        sys.exit(1)
