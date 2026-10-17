"""Refuse to publish or merge source that contains absolute host paths.

A repository that hardcodes `C:/Users/<name>/...` or `D:/Some-Machine-Root/...`
cannot be cloned and used, and it leaks the developer's directory layout. This
check scans everything that ships and fails on the first hit.

It shares its allowlist and exemptions with tools/build_publication_bundle.py so
that "what CI checks" and "what gets published" cannot drift apart.

Exit codes: 0 clean; 1 host paths found; 2 the check could not run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

SCANNED_TREES = ('src', 'tests', 'configs', 'experiments', 'model_packages', 'frontend')
SCANNED_SUFFIXES = frozenset({'.py', '.json', '.yaml', '.yml', '.toml', '.md', '.ts', '.tsx',
                              '.js', '.html', '.csv', '.lean'})
SKIP_DIR_NAMES = frozenset({'__pycache__', '.lake', 'node_modules', '.pytest_cache', 'dist',
                            'test-results', 'playwright-report'})

# Exemptions are explicit and reasoned; an unexplained exemption is a hole.
EXEMPT_FILES = {
    # Machine-specific by design and never published (.example ships instead).
    'configs/discovery/proof-backend-host.json':
        'declares this host\'s optional proof backend location; gitignored',
    # These three define or rewrite the very patterns being searched for, so they
    # must mention them. Nothing else may.
    'tools/check_portability.py': 'defines the host-path pattern it searches for',
    'tools/build_publication_bundle.py': 'defines the prefix-rewriting rules it applies',
    'tools/repin_proof_backend_portability_20261017.py':
        'defines the host-path pattern it verifies against',
    'tools/normalize_fixture_host_paths_20261017.py':
        'counts occurrences of the username pattern it removes',
}
EXEMPT_PATH_PREFIXES = {
    'docs/STATUS.md': 'internal append-only session log; not published',
    'docs/PROGRESS_REPORT_': 'internal engineering log; historical host paths kept verbatim',
    # Historical "next command" records inside the design log. The published copy
    # is normalized by tools/build_publication_bundle.py; the working tree keeps
    # the commands exactly as they were run.
    'PLANS.md': 'historical command records; normalized in the published copy only',
}

HOST_PATH = re.compile(
    r'[A-Za-z]:[/\\]{1,2}Users[/\\]{1,2}'
    r'|[A-Za-z]:[/\\]{1,2}Naheng-'
    r'|Lee Master'
    r'|C:[/\\]{1,2}Windows[/\\]{1,2}System32')


def is_exempt(relative: str) -> bool:
    if relative in EXEMPT_FILES:
        return True
    return any(relative.startswith(prefix) for prefix in EXEMPT_PATH_PREFIXES)


def scan(tools_allowlist: frozenset[str] = frozenset()):
    hits = []
    candidates = []
    for tree in SCANNED_TREES:
        base = ROOT / tree
        if base.is_dir():
            candidates += [p for p in sorted(base.rglob('*')) if p.is_file()]
    tools_dir = ROOT / 'tools'
    if tools_dir.is_dir():
        wanted = tools_allowlist or {p.name for p in tools_dir.glob('*.py')}
        candidates += [p for p in sorted(tools_dir.glob('*.py')) if p.name in wanted]
    for name in ('README.md', 'CONTRIBUTING.md', 'AGENTS.md', 'PLANS.md'):
        path = ROOT / name
        if path.is_file():
            candidates.append(path)

    for path in candidates:
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if is_exempt(relative):
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            match = HOST_PATH.search(line)
            if match:
                hits.append({'path': relative, 'line': number, 'match': match.group(0),
                             'text': line.strip()[:160]})
    return hits


def load_publication_allowlist():
    """Read the tool allowlist from the publication builder so the two agree."""
    builder = ROOT / 'tools' / 'build_publication_bundle.py'
    if not builder.is_file():
        return None
    source = builder.read_text(encoding='utf-8')
    start = source.index('TOOLS_ALLOWLIST = frozenset({')
    end = source.index('})', start) + 2
    namespace = {}
    exec(compile(source[start:end], str(builder), 'exec'), namespace)  # noqa: S102
    return frozenset(namespace['TOOLS_ALLOWLIST'])


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--all-tools', action='store_true',
                        help='also scan tools that the publication builder excludes '
                             '(internal audit; the excluded one-off session scripts '
                             'legitimately contain host paths)')
    arguments = parser.parse_args()

    allowlist = None if arguments.all_tools else load_publication_allowlist()
    if allowlist is None and not arguments.all_tools:
        print(json.dumps({'status': 'builder_missing',
                          'expected': str(ROOT / 'tools' / 'build_publication_bundle.py')}))
        return 2
    hits = scan(allowlist or frozenset())
    report = {'tool': Path(__file__).name, 'host_path_hits': len(hits), 'clean': not hits,
              'scanned_trees': list(SCANNED_TREES),
              'tools_scope': 'all' if arguments.all_tools else 'publication_allowlist',
              'tools_allowlist_size': None if allowlist is None else len(allowlist),
              'exempt_files': EXEMPT_FILES,
              'exempt_path_prefixes': EXEMPT_PATH_PREFIXES,
              'hits': hits[:50]}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if not hits else 1


if __name__ == '__main__':
    raise SystemExit(main())
