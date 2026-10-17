"""List artifacts that tests read at runtime but the publication bundle omits."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r'artifacts[/\\][A-Za-z0-9._\-]+(?:[/\\][A-Za-z0-9._\-]+)*')


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    staging = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    refs = set()
    for path in (ROOT / 'tests').rglob('*.py'):
        text = path.read_text(encoding='utf-8', errors='replace')
        for match in PATTERN.findall(text):
            refs.add(match.replace('\\', '/'))
    exists = sorted(r for r in refs if (ROOT / r).exists())
    print(f'test-referenced artifact paths: {len(refs)}')
    print(f'  exist in working tree:        {len(exists)}')
    if staging is None:
        for r in exists:
            print('   ', r)
        return 0
    missing = [r for r in exists if not (staging / r).exists()]
    print(f'  absent from bundle:           {len(missing)}')
    total = 0
    for r in missing:
        path = ROOT / r
        size = path.stat().st_size if path.is_file() else sum(
            f.stat().st_size for f in path.rglob('*') if f.is_file())
        total += size
        print(f'   {size/1024:9.1f}KiB  {r}')
    print(f'  total missing: {total/1024:.1f}KiB')
    return 0 if not missing else 1


if __name__ == '__main__':
    raise SystemExit(main())
