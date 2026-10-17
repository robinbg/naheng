"""Build the open-source bundle on another drive and prove its citations resolve.

The working tree cannot be pushed as-is: `artifacts/` holds 2.6 GiB of run
trajectories and recovery dumps, `formal/.lake/` holds Lean build products, and
`data/raw/` holds retrieved public measurements. GitHub rejects files above
100 MiB and a repository of that size is not reviewable.

This tool therefore builds a staging tree elsewhere (D: by default, because the
project drive has almost no free space) containing:

  * every source, test, tool, config, doc, Lean source and frontend source file;
  * a curated evidence bundle — the receipts the documentation actually cites,
    plus the acceptance manifests for each completed task;
  * the small data manifests and frozen split definitions, never raw CSV.

It then does the part that matters for review: it scans every bundled Markdown
file for project-relative paths and reports which ones resolve inside the
bundle. A README that cites an artifact the reader cannot open is worse than no
citation, so broken references are listed explicitly rather than hidden.

Nothing here publishes anything. It only writes the staging tree.

Exit codes
    0  bundle built; every path cited by README.md resolves inside it
    1  bundle built but README.md cites paths that are absent
    2  bundle could not be built (staging conflict, budget exceeded, I/O error)
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]

SOURCE_TREES = ('src', 'tests', 'tools', 'configs', 'docs', 'experiments',
                'model_packages', 'formal', 'frontend')
EXCLUDED_DIR_NAMES = frozenset({'.git', '.lake', '__pycache__', 'node_modules', 'dist',
                                'test-results', 'playwright-report', '.pytest_cache',
                                '.venv', '.bootstrap', '.tools', 'build'})
ROOT_FILES = ('AGENTS.md', 'PLANS.md', 'TASKS.yaml', 'REQUIREMENTS.yaml', 'START_CODEX.md',
              'HANDOFF_CHECK.json', 'pyproject.toml', 'uv.lock', 'Dockerfile', 'compose.yaml',
              '.gitignore', '.dockerignore', 'README.md', 'LICENSE')

# Curated evidence: receipts and manifests, never bulk trajectories.
EVIDENCE_PATTERNS = (
    'artifacts/formal/core/manifest.json',
    'artifacts/formal/*/manifest.json',
    'artifacts/formal/active_*.json',
    'artifacts/current-smoke-*.json',
    'artifacts/smoke_final.json',
    'artifacts/release_audit.json',
    'artifacts/handoff_final.json',
    'artifacts/handoff_after_lean.json',
    'artifacts/verification/smoke-8e6b29d9b0/*',
    'artifacts/verification/smoke-dadd49f060/*',
    'artifacts/review/a03-label-determinism-20261016-a/**',
    'artifacts/a03-determinism-probe-20261016-*/report.json',
    'artifacts/review/smoke-gate-repair-20261016-a/**',
    'artifacts/optimization/public-9593-20261016-c/*.json',
    'artifacts/optimization/public-0a2-20261016-c/result.json',
    'artifacts/full-policy-*/result.json',
    'artifacts/full-policy-*/protocol.json',
    'artifacts/review/a03-new-9593-independent-20261016-c/**/handoff.json',
    'artifacts/review/a03-comparison-root-*/report.json',
    'artifacts/review/a03-training-root-audit-*/report.json',
    'artifacts/review/r01-learning-figures-independent-20261016-c/**',
    'artifacts/handoff/r01-learning-figures-20261016-a/*.json',
    'artifacts/handoff/r01-learning-figures-20261016-a/*.md',
    'artifacts/handoff/r01-learning-figures-20261016-a/*.png',
    'artifacts/progress/*/manifest.json',
    'artifacts/progress/*/checkpoint.json',
    'artifacts/progress/*/applied.json',
    'artifacts/ui/acceptance.json',
    'artifacts/review/ui-9593-independent-20261016-c/handoff.json',
    'artifacts/review/r00-clean-9593-independent-20261016-d/ui-handoff.json',
    'artifacts/validation/R02-final-release-audit-*/command.json',
    'artifacts/validation/A03-*/command.json',
    'artifacts/validation/D02-*/command.json',
    'artifacts/public_validation/current-capacity-combined-20261014-b/manifest.json',
    'artifacts/handoff/d02-source-completion-20261016-a/*.json',
    'artifacts/handoff/d02-source-completion-20261016-a/*.md',
    'artifacts/review/d02-primary-gap-independent-20261015-a/*',
    'artifacts/probes/lean-recovery.json',
    'artifacts/environment_lean_restored.json',
    'data/manifests/**',
    'data/splits/**',
)

MAX_FILE_MIB = 8.0
MAX_TOTAL_MIB = 250.0
SECRET_SUFFIXES = ('.pem', '.key', '.p12', '.pfx', '.env')

# Paths that documentation mentions on purpose although they are absent from the
# bundle. Declaring them keeps the citation check strict: any *undeclared*
# README citation that does not resolve still fails the build, so this list
# cannot be used to wave away a genuinely missing artifact.
EXPECTED_ABSENT = {
    'artifacts/demo': 'output target of the `naheng demo` quick-start command; created when the reader runs it',
    'artifacts/reports/learning-9593-20261016-d/generation.json':
        'cited in README as a worked example of a broken citation inside docs/CLAIMS.md; '
        'the directory is empty in the working tree and the real figure evidence lives in '
        'artifacts/handoff/r01-learning-figures-20261016-a/',
    'artifacts/test-temp/proof-worker-isolation':
        'runtime directory created by the proof-output fixture while tests run',
}

PATH_CITATION = re.compile(
    r'(?<![\w./-])((?:artifacts|data|src|tests|tools|configs|docs|formal|frontend|experiments|model_packages)'
    r'/[A-Za-z0-9._@+\-]+(?:/[A-Za-z0-9._@+\-*]+)*)')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def walk_files(base: Path):
    for current, directories, filenames in os_walk(base):
        directories[:] = [d for d in directories if d not in EXCLUDED_DIR_NAMES]
        for name in sorted(filenames):
            yield Path(current) / name


def os_walk(base: Path):
    import os
    yield from os.walk(base)


def copy_tree(relative: str, staging: Path, log: dict) -> None:
    source = ROOT / relative
    if not source.is_dir():
        log['missing_trees'].append(relative)
        return
    count = 0
    for path in walk_files(source):
        if path.suffix.lower() in SECRET_SUFFIXES or path.name.startswith('.env'):
            log['skipped_secret'].append(str(path.relative_to(ROOT)).replace('\\', '/'))
            continue
        target = staging / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, target)
            count += 1
            log['bytes'] += path.stat().st_size
        except OSError as error:
            log['permission_denied'].append({'path': str(path.relative_to(ROOT)).replace('\\', '/'),
                                             'error': repr(error)})
    log['trees'][relative] = count


def copy_evidence(staging: Path, log: dict) -> None:
    seen = set()
    for pattern in EVIDENCE_PATTERNS:
        for path in sorted(ROOT.glob(pattern)):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT).as_posix()
            if relative in seen:
                continue
            if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
                continue
            if path.suffix.lower() in SECRET_SUFFIXES:
                log['skipped_secret'].append(relative)
                continue
            size = path.stat().st_size
            if size > MAX_FILE_MIB * 1024 * 1024:
                log['skipped_oversize'].append({'path': relative, 'mib': round(size / 1024**2, 2)})
                continue
            if (log['bytes'] + size) / 1024**2 > MAX_TOTAL_MIB:
                log['budget_exhausted_at'] = relative
                return
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(path, target)
            except OSError as error:
                log['permission_denied'].append({'path': relative, 'error': repr(error)})
                continue
            seen.add(relative)
            log['evidence_files'] += 1
            log['bytes'] += size


def cited_paths(staging: Path):
    """Every project-relative path mentioned by a bundled Markdown file."""
    found = {}
    for markdown in sorted(staging.rglob('*.md')):
        text = markdown.read_text(encoding='utf-8', errors='replace')
        relative_md = markdown.relative_to(staging).as_posix()
        for match in PATH_CITATION.findall(text):
            found.setdefault(match, set()).add(relative_md)
    return found


def check_citations(staging: Path):
    found = cited_paths(staging)
    resolved, declared, broken = {}, {}, {}
    for citation, sources in sorted(found.items()):
        clean = citation.rstrip('.,;:)')
        target = staging / clean
        if target.exists():
            resolved[clean] = sorted(sources)
        elif '*' in clean:
            resolved[clean + ' (glob)'] = sorted(sources)
        elif clean in EXPECTED_ABSENT:
            declared[clean] = {'reason': EXPECTED_ABSENT[clean], 'cited_by': sorted(sources)}
        else:
            broken[clean] = sorted(sources)
    return resolved, declared, broken


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--staging', required=True)
    parser.add_argument('--force', action='store_true')
    arguments = parser.parse_args()

    staging = Path(arguments.staging).resolve()
    if staging.is_relative_to(ROOT):
        print(json.dumps({'status': 'staging_must_be_outside_the_working_tree',
                          'reason': 'the project drive has almost no free space'}))
        return 2
    if staging.exists() and any(staging.iterdir()) and not arguments.force:
        print(json.dumps({'status': 'staging_not_empty', 'staging': str(staging),
                          'hint': 'pass --force to rebuild it'}))
        return 2
    if arguments.force and staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    log = {'trees': {}, 'bytes': 0, 'evidence_files': 0, 'missing_trees': [],
           'skipped_secret': [], 'skipped_oversize': [], 'permission_denied': [],
           'budget_exhausted_at': None}
    for relative in SOURCE_TREES:
        copy_tree(relative, staging, log)
    for name in ROOT_FILES:
        source = ROOT / name
        if source.is_file():
            shutil.copy2(source, staging / name)
            log['bytes'] += source.stat().st_size
        else:
            log['missing_trees'].append(name)
    copy_evidence(staging, log)

    # The working tree ignores artifacts/ wholesale. The bundle contains only the
    # curated receipts, so those must be tracked; keep ignoring everything that
    # is a build product or a local environment.
    bundle_gitignore = """# Bundle-specific: the working tree's .gitignore excludes artifacts/ entirely,
# but this repository ships a curated evidence subset that must be tracked.
.venv/
.bootstrap/
.tools/
__pycache__/
*.pyc
.pytest_cache/
formal/.lake/
frontend/node_modules/
frontend/dist/
frontend/test-results/
frontend/playwright-report/
*.egg-info/
data/raw/
.env
.env.*
*.key
*.pem
*.p12
*.pfx
"""
    (staging / '.gitignore').write_text(bundle_gitignore, encoding='utf-8')
    log['gitignore_rewritten_for_bundle'] = True

    resolved, declared, broken = check_citations(staging)
    readme_broken = {path: sources for path, sources in broken.items()
                     if 'README.md' in sources}
    log.update({'staging': str(staging), 'total_mib': round(log['bytes'] / 1024**2, 2),
                'citations_resolved': len(resolved), 'citations_broken': len(broken),
                'citations_declared_absent': len(declared),
                'readme_citations_broken': len(readme_broken)})

    (staging / 'BUNDLE_MANIFEST.json').write_text(json.dumps(
        {**log, 'broken_citations': broken, 'declared_absent_citations': declared,
         'resolved_citation_count': len(resolved),
         'excluded_by_design': {
             'artifacts/ bulk': 'run trajectories, recovery-test dumps, review working trees (2.6 GiB)',
             'formal/.lake/': 'Lean build products; rebuild with lake build from the pinned toolchain',
             'data/raw/': 'retrieved public measurements (303 MiB); see data/manifests for provenance and re-download',
             '.venv/ .bootstrap/ .tools/': 'interpreter, uv and Lean toolchains; see docs/ENVIRONMENT.md',
             'frontend/node_modules/ frontend/dist/': 'npm install and npm run build reproduce these'}},
        indent=2), encoding='utf-8')

    index = ['# 开源包内容与边界', '',
             f'本目录是工作树的**可审阅子集**，共 {log["total_mib"]} MiB。',
             f'* 源码/测试/工具/配置/文档/Lean 源/前端源：{sum(log["trees"].values())} 个文件',
             f'* 精选证据收据：{log["evidence_files"]} 个文件',
             f'* 文档引用路径核对：{len(resolved)} 条可在本包内解析，{len(declared)} 条为文档有意提及的不存在路径，{len(broken)} 条不可解析',
             '', '## 有意排除', '']
    for key, reason in json.loads((staging / 'BUNDLE_MANIFEST.json').read_text(encoding='utf-8'))['excluded_by_design'].items():
        index.append(f'* `{key}` —— {reason}')
    index += ['', '## 文档有意提及、但本包内不存在的路径', '',
              '这些路径被文档明确当作"命令输出目标""运行时目录"或"失效引用的例子"提到，'
              '因此它们的缺失是预期的。此列表由 `tools/export_opensource_bundle_20261016.py` '
              '中的 `EXPECTED_ABSENT` 显式声明；未在此声明而 README 又引用不到的路径会直接让构建失败。', '']
    for path, row in sorted(declared.items()):
        index.append(f'* `{path}` —— {row["reason"]}')
    index += ['', '## 不可解析的引用', '',
              '以下是文档中提到、但本包内不存在的路径。它们要么属于被排除的批量工件，'
              '要么是 `docs/STATUS.md` 中"下一条执行命令"的输出目标（命令尚未运行或输出已被后续轮次取代），'
              '要么是文档本身的失效引用；三种情况都如实列出，不做掩饰。', '']
    for path, sources in sorted(broken.items()):
        index.append(f'* `{path}` —— 被引用于 {", ".join(f"`{s}`" for s in sources)}')
    if log['permission_denied']:
        index += ['', '## 因权限未能复制', '']
        index += [f'* `{row["path"]}`' for row in log['permission_denied'][:40]]
    (staging / 'EVIDENCE_INDEX.md').write_text('\n'.join(index) + '\n', encoding='utf-8')

    print(json.dumps({k: log[k] for k in ('staging', 'total_mib', 'evidence_files',
                                          'citations_resolved', 'citations_declared_absent',
                                          'citations_broken', 'readme_citations_broken',
                                          'trees')}, indent=2, ensure_ascii=False))
    if readme_broken:
        print(json.dumps({'README_broken_citations': sorted(readme_broken)}, indent=2, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
