"""Release helpers for CHANGELOG.md, used by .github/workflows/release.yml.

  changelog.py roll VERSION DATE NOTES   Move "## Unreleased" into "## VERSION - DATE", leave an
                                         empty "## Unreleased" above it, write the section to NOTES.
  changelog.py notes VERSION NOTES       Write the existing "## VERSION ..." section to NOTES.

Both fail if the section is missing or empty, so a release never ships with blank notes.
"""
import re
import sys
from pathlib import Path

CHANGELOG = Path('CHANGELOG.md')


def section(lines, heading):
    """Return (start, end) line indexes of the body under the first heading matching `heading`."""
    for index, line in enumerate(lines):
        if re.match(heading, line):
            end = next((i for i in range(index + 1, len(lines)) if lines[i].startswith('## ')), len(lines))
            return index, end
    sys.exit(f'CHANGELOG.md has no section matching {heading!r}')


def body(lines, start, end):
    text = ''.join(lines[start + 1:end]).strip()
    if not text:
        sys.exit(f'CHANGELOG.md section {lines[start].strip()!r} is empty')
    return text + '\n'


def main(command, version, *args):
    lines = CHANGELOG.read_text().splitlines(keepends=True)
    if command == 'roll':
        date, notes = args
        if any(re.match(rf'## {re.escape(version)}(\s|$)', line) for line in lines):
            sys.exit(f'CHANGELOG.md already has a {version} section')
        start, end = section(lines, r'## Unreleased\s*$')
        text = body(lines, start, end)
        lines[start:end] = ['## Unreleased\n', '\n', f'## {version} - {date}\n', '\n', text, '\n']
        CHANGELOG.write_text(''.join(lines).rstrip('\n') + '\n')
    elif command == 'notes':
        notes, = args
        start, end = section(lines, rf'## {re.escape(version)}(\s|$)')
        text = body(lines, start, end)
    else:
        sys.exit(f'unknown command {command!r}')
    Path(notes).write_text(text)


if __name__ == '__main__':
    main(*sys.argv[1:])
