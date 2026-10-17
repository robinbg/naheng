"""Build the public repository bundle: curated, portable, and citation-checked.

Dumping the working tree is not open source. A clone has to install, run and be
contributable, so this builder applies four rules and reports what it did:

1. **Curate.** `tools/` holds 257 scripts, most of them one-off session
   scaffolding. Only an explicit allowlist ships. Internal agent-orchestration
   files (`START_CODEX.md`, `HANDOFF_CHECK.json`) and the 700-line append-only
   session log do not ship; a concise status overview is generated instead.

2. **Normalize.** Evidence receipts record absolute paths from the machine that
   produced them. Every copied text file has the project root and the host
   backend/temp roots rewritten to `<PROJECT_ROOT>`, `<HOST_BACKEND_ROOT>` and
   `<HOST_TEMP_ROOT>`. The rule and a per-file SHA256 of the original are
   recorded so the transform is auditable and reversible. Normalization is
   applied to copies only; the working tree is never rewritten.

3. **Prove portability.** No shipped source, test, tool or config may contain an
   absolute host path. `tools/repin_proof_backend_portability_20261017.py`
   enforces this over the same allowlist.

4. **Check citations.** Every project-relative path mentioned by a bundled
   Markdown file is verified to resolve inside the bundle, except paths declared
   in `EXPECTED_ABSENT`. An undeclared broken README citation fails the build.

Nothing here publishes anything; it only writes the staging tree.

Exit codes: 0 built and README citations resolve; 1 README cites absent paths;
2 the bundle could not be built.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]

SOURCE_TREES = ('src', 'tests', 'configs', 'experiments', 'model_packages', 'formal', 'frontend')
EXCLUDED_DIR_NAMES = frozenset({'.git', '.lake', '__pycache__', 'node_modules', 'dist',
                                'test-results', 'playwright-report', '.pytest_cache',
                                '.venv', '.bootstrap', '.tools', 'build'})
SECRET_SUFFIXES = ('.pem', '.key', '.p12', '.pfx')

# Gitignored in the published tree, so never copied: staging must match exactly
# what a clone receives, rather than relying on .gitignore to hide a file that
# is physically present.
NEVER_PUBLISHED = frozenset({'configs/discovery/proof-backend-host.json'})

ROOT_FILES = ('README.md', 'LICENSE', 'CONTRIBUTING.md', 'AGENTS.md', 'PLANS.md',
              'TASKS.yaml', 'REQUIREMENTS.yaml', 'pyproject.toml', 'uv.lock',
              'Dockerfile', 'compose.yaml', '.dockerignore')
EXTRA_TREES = ('.github',)

# Curated tools: referenced by configs/gates.yaml, tests or docs, plus the
# diagnosis/reproduction utilities this publication documents. The 226 excluded
# scripts are one-off session scaffolding and stay in the working tree.
TOOLS_ALLOWLIST = frozenset({
    'audit_formal.py', 'build_delivery.py', 'build_frontend.py',
    'check_current_partial_publications.py', 'check_current_trajectory_publication.py',
    'check_handoff.py', 'check_release.py', 'check_ui_acceptance.py', 'check_portability.py',
    'compare_full_policy_queries_20261016.py', 'container_entry.py',
    'data_source_integration.py', 'diagnose_a03_label_determinism_20261016.py',
    'evidence_report.py', 'export_opensource_bundle_20261016.py',
    'build_publication_bundle.py', 'fetch_cache_parallel.py',
    'inspect_residual_publication_inputs.py', 'probe_a03_label_determinism_20261016.py',
    'probe_backends.py', 'record_execution_checkpoint.py',
    'refresh_runtime_proof_publications.py',
    'repin_proof_backend_encoding_repair_20261016.py',
    'repin_proof_backend_portability_20261017.py',
    'run_confirmed_validation.py', 'run_current_source_regression.py', 'run_evidence.py',
    'run_owned_validation.py', 'setup_lean_dependencies.py', 'start_local.py',
    'validate_additional_zenodo_csv.py', 'validate_zenodo_csv.py',
    'normalize_fixture_host_paths_20261017.py', 'check_portability.py',
    'list_test_artifact_gaps_20261017.py',
})

# Docs that ship. The append-only session log is replaced by a generated overview.
DOCS_EXCLUDE = frozenset({'STATUS.md', 'HANDOFF_PACKAGE_README.md'})

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
    'artifacts/review/publication-portability-20261017-a/**',
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
    'artifacts/review/d02-public-entry-review-a/**',
    'artifacts/review/capacity-protocol-proposed-change-20261013/original_capacity_protocol.py',
    # Runtime input read by a test. The retrieved CSVs beside it are third-party
    # data and stay out, exactly like data/raw/.
    'artifacts/data/public_new/*.json',
    'artifacts/data/public_new/*.md',
    # Deliberately NOT shipped: the data-integration registry chain
    # (data-integration-*/handoff.json, report.json, audit.json,
    #  artifacts/data/public_independent/**, D01 validation receipts). It ends in
    # derived views of a third-party public dataset that is not redistributed, so
    # only half the chain would be verifiable. Publishing the receipts also means
    # publishing them byte-exact — they are SHA-pinned — which would publish the
    # producing host's paths. naheng.data.registry_availability makes the
    # resulting external data dependency explicit and the affected tests skip
    # with a reason instead of passing vacuously.
    'artifacts/data/public_new/*.json',
    'artifacts/data/public_new/*.md',
    'artifacts/calibration/builtin-calibration-current-20261014-f/**',
    'artifacts/lifecycle_validation/*.json',
    'artifacts/progress/*/manifest.json',
    'artifacts/progress/*/checkpoint.json',
    'artifacts/progress/*/applied.json',
    'artifacts/ui/acceptance.json',
    'artifacts/review/ui-9593-independent-20261016-c/handoff.json',
    'artifacts/review/r00-clean-9593-independent-20261016-d/ui-handoff.json',
    'artifacts/validation/R02-final-release-audit-*/command.json',
    'artifacts/validation/A03-*/command.json',
    'artifacts/probes/lean-recovery.json',
    'artifacts/environment_lean_restored.json',
    'data/manifests/**',
    'data/splits/**',
)

MAX_FILE_MIB = 8.0
MAX_TOTAL_MIB = 400.0
# The registry closure ends in ~400 MiB of derived views of a third-party public
# dataset. Those are not redistributed, for the same reason data/raw/ is not, so
# only the small receipts ship. naheng.data.registry_availability makes the
# resulting external data dependency explicit, and the affected tests skip with a
# reason rather than passing vacuously.
MAX_PINNED_FILE_MIB = 1.0

# Machine-specific prefixes rewritten in copies. Separators are written as
# [/\\]{1,2} because evidence receipts contain literal paths, JSON-escaped paths
# (where every backslash is doubled) and forward-slash paths alike. Longest first.
NORMALIZATIONS = (
    (r'(?:[\\]{2,4}\?[\\]{1,2})?C:[/\\]{1,2}Users[/\\]{1,2}Lee Master[/\\]{1,2}Documents[/\\]{1,2}'
     r'Codex[/\\]{1,2}2026-10-09[/\\]{1,2}agents-md-plans-md-tasks-yaml[/\\]{1,2}outputs[/\\]{1,2}naheng',
     '<PROJECT_ROOT>'),
    (r'C:[/\\]{1,2}Users[/\\]{1,2}Lee Master', '<HOST_HOME>'),
    (r'D:[/\\]{1,2}Naheng-Research-VM-[0-9A-Za-z\-]+', '<HOST_BACKEND_ROOT>'),
    (r'D:[/\\]{1,2}Naheng-Maintenance', '<HOST_MAINTENANCE_ROOT>'),
    (r'D:[/\\]{1,2}Naheng-Delivery-Validation-[0-9A-Za-z\-]+', '<HOST_DELIVERY_ROOT>'),
    (r'D:[/\\]{1,2}Naheng-[0-9A-Za-z\-]+', '<HOST_DATA_ROOT>'),
    (r'D:[/\\]{1,2}nh[0-9A-Za-z\-]*', '<HOST_TEMP_ROOT>'),
    # Bare occurrences of the account name in prose or logs, caught last.
    (r'Lee Master', '<HOST_USER>'),
)
NORMALIZATION_RULES = [(re.compile(pattern), replacement) for pattern, replacement in NORMALIZATIONS]
# Applied to the staged tree after copying, to verify rather than assume.
# Deliberately narrower than check_portability.HOST_PATH: this scan looks for
# machine-specific or personally identifying locations in published evidence.
# `C:/Windows/System32` is neither — it exists identically on every Windows host
# and legitimately appears inside diffs and pre-repair backups as a historical
# record. Hardcoding it in *source* is still caught by check_portability.py.
RESIDUAL_HOST_PATH = re.compile(
    r'[A-Za-z]:[/\\]{1,2}Users[/\\]{1,2}'
    r'|Lee Master'
    r'|[A-Za-z]:[/\\]{1,2}Naheng-')
TEXT_SUFFIXES = frozenset({'.json', '.md', '.txt', '.log', '.yaml', '.yml', '.py', '.toml',
                           '.csv', '.html', '.ts', '.tsx', '.js', '.lean'})

EXPECTED_ABSENT = {
    'artifacts/demo': 'output target of the `naheng demo` quick-start command; created when the reader runs it',
    'artifacts/reports/learning-9593-20261016-d/generation.json':
        'cited in README as a worked example of a broken citation inside docs/CLAIMS.md; the '
        'directory is empty in the working tree and the real figure evidence lives in '
        'artifacts/handoff/r01-learning-figures-20261016-a/',
    'artifacts/test-temp/proof-worker-isolation':
        'runtime directory created by the proof-output fixture while tests run',
    'artifacts/calibration': 'runtime parent directory; a .gitkeep keeps it present for tests that create packets in it',
    'docs/STATUS.md': 'the 700-line append-only session log is internal; docs/STATUS_OVERVIEW.md is published instead',
}

PATH_CITATION = re.compile(
    r'(?<![\w./-])((?:artifacts|data|src|tests|tools|configs|docs|formal|frontend|experiments|model_packages)'
    r'/[A-Za-z0-9._@+\-]+(?:/[A-Za-z0-9._@+\-*]+)*)')


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def normalize_bytes(data: bytes, suffix: str):
    """Rewrite machine-specific prefixes. Returns (bytes, changed)."""
    if suffix.lower() not in TEXT_SUFFIXES:
        return data, False
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return data, False
    original = text
    for pattern, replacement in NORMALIZATION_RULES:
        text = pattern.sub(replacement, text)
    if text == original:
        return data, False
    return text.encode('utf-8'), True


def copy_one(source: Path, target: Path, log: dict, relative: str, normalize: bool) -> bool:
    if source.suffix.lower() in SECRET_SUFFIXES or source.name.startswith('.env'):
        log['skipped_secret'].append(relative)
        return False
    try:
        data = source.read_bytes()
    except OSError as error:
        log['permission_denied'].append({'path': relative, 'error': repr(error)})
        return False
    changed = False
    if normalize:
        data, changed = normalize_bytes(data, source.suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    log['bytes'] += len(data)
    if changed:
        log['normalized_files'] += 1
        log['normalization_sha256_original'][relative] = sha256_bytes(source.read_bytes())
    return True


def walk_files(base: Path):
    import os
    for current, directories, filenames in os.walk(base):
        directories[:] = [d for d in directories if d not in EXCLUDED_DIR_NAMES]
        for name in sorted(filenames):
            yield Path(current) / name


def display_rules():
    """The rules as documented for readers, with the account name redacted.

    The authoritative regular expressions live in this module and must name the
    literal prefix to match it. Everything *derived* — the manifest, the evidence
    index — describes the same transform without republishing the identifier the
    transform exists to remove.
    """
    return [{'pattern': pattern.replace('Lee Master', '<HOST_USER>'), 'replacement': replacement}
            for pattern, replacement in NORMALIZATIONS]


def _portability_exemptions():
    """Load the exemption sets from check_portability.py (one source of truth)."""
    import importlib.util
    checker = ROOT / 'tools' / 'check_portability.py'
    spec = importlib.util.spec_from_file_location('check_portability', checker)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module.EXEMPT_FILES), tuple(module.EXEMPT_PATH_PREFIXES)


def _collect_strings(value, out):
    """Every string appearing as a key or a value, at any depth."""
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                out.add(key)
            _collect_strings(item, out)
    elif isinstance(value, list):
        for item in value:
            _collect_strings(item, out)
    elif isinstance(value, str):
        out.add(value)


def registry_pinned_paths():
    """Transitive closure of files whose bytes the frozen data registry pins.

    `data/manifests/sources.yaml` records a SHA256 for each evidence receipt in
    the data-integration chain, and those receipts pin further files in turn
    (`public_files_sha256`, per-member `member_manifest`, unit views). Missing or
    rewritten bytes make `validate_new_source` refuse to run, so the whole closure
    has to ship byte-exact.

    References appear with both `/` and `\\` separators, so this walks the parsed
    documents instead of pattern-matching paths out of raw text: a regex over the
    YAML silently missed the backslash form and left three tests red.
    """
    seeds = [ROOT / 'data' / 'manifests' / 'sources.yaml']
    found = {}
    frontier = [path for path in seeds if path.is_file()]
    for _ in range(6):  # bounded closure; the chain is shallow
        following = []
        for document in frontier:
            try:
                text = document.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                # The closure reaches binary payloads too (compressed members,
                # compiled objects). They are pinned, just not followable.
                continue
            data = None
            try:
                data = json.loads(text)
            except ValueError:
                try:
                    import yaml
                    data = yaml.safe_load(text)
                except Exception:  # noqa: BLE001 - unparsable seeds are simply skipped
                    data = None
            if data is None:
                continue
            strings = set()
            _collect_strings(data, strings)
            for candidate in strings:
                relative = candidate.replace('\\', '/').strip()
                if not relative.startswith(('artifacts/', 'data/')):
                    continue
                if '*' in relative or ' ' in relative or relative.endswith('/'):
                    continue
                path = ROOT / relative
                if path.is_file() and relative not in found:
                    found[relative] = path.stat().st_size
                    if path.suffix.lower() in ('.json', '.yaml', '.yml'):
                        following.append(path)
        frontier = following
        if not frontier:
            break
    return found


def force_rmtree(path: Path) -> None:
    """Remove a tree even when it contains read-only files.

    Git stores its objects read-only, so a plain rmtree fails with
    PermissionError on Windows as soon as a .git directory exists in staging.
    """
    import os
    import stat

    def handler(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=handler)
    else:
        shutil.rmtree(path, onerror=lambda func, target, exc: handler(func, target, exc))


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--staging', required=True)
    parser.add_argument('--force', action='store_true')
    arguments = parser.parse_args()

    staging = Path(arguments.staging).resolve()
    if staging.is_relative_to(ROOT):
        print(json.dumps({'status': 'staging_must_be_outside_the_working_tree'}))
        return 2
    if staging.exists() and any(staging.iterdir()) and not arguments.force:
        print(json.dumps({'status': 'staging_not_empty', 'staging': str(staging), 'hint': 'pass --force'}))
        return 2
    if staging.exists():
        force_rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    log = {'trees': {}, 'bytes': 0, 'evidence_files': 0, 'source_files': 0,
           'missing': [], 'skipped_secret': [], 'skipped_oversize': [], 'permission_denied': [],
           'normalized_files': 0, 'normalization_sha256_original': {}, 'tools_excluded': 0,
           'not_published': [], 'budget_exhausted_at': None}

    # 1. Source trees, copied byte-exact: they must already be portable.
    for relative in SOURCE_TREES:
        base = ROOT / relative
        if not base.is_dir():
            log['missing'].append(relative)
            continue
        count = 0
        for path in walk_files(base):
            name = path.relative_to(ROOT).as_posix()
            if name in NEVER_PUBLISHED:
                log['not_published'].append(
                    {'path': name,
                     'reason': 'host-specific backend location; gitignored, .example ships instead'})
                continue
            if copy_one(path, staging / name, log, name, normalize=False):
                count += 1
        log['trees'][relative] = count
        log['source_files'] += count

    # 2. Fixture inputs the calibration tests read and hash-pin. These are copied
    # byte-exact by the tests tree above; they are deliberately NOT normalized,
    # because test_calibration_runtime.py asserts the SHA256 of each listed
    # fixture and rewriting a byte would break that assertion. They were made
    # portable at source instead (tools/normalize_fixture_host_paths_20261017.py)
    # and are covered by the portability scan.
    for extra in ('data/synthetic/**', 'artifacts/calibration/prepared-builtin-1977f8a08879/**'):
        for path in sorted(ROOT.glob(extra)):
            if path.is_file():
                relative = path.relative_to(ROOT).as_posix()
                if not (staging / relative).exists():
                    copy_one(path, staging / relative, log, relative, normalize=False)
                    log['evidence_files'] += 1

    # 3. Curated tools.
    tools_dir = ROOT / 'tools'
    kept = 0
    for path in sorted(tools_dir.glob('*.py')):
        if path.name in TOOLS_ALLOWLIST:
            if copy_one(path, staging / 'tools' / path.name, log, 'tools/' + path.name, normalize=False):
                kept += 1
        else:
            log['tools_excluded'] += 1
    log['trees']['tools'] = kept
    log['source_files'] += kept
    missing_tools = sorted(TOOLS_ALLOWLIST - {p.name for p in tools_dir.glob('*.py')})
    log['allowlisted_tools_absent'] = missing_tools

    # 4. Curated docs.
    docs_count = 0
    for path in walk_files(ROOT / 'docs'):
        if path.parent == ROOT / 'docs' and path.name in DOCS_EXCLUDE:
            continue
        name = path.relative_to(ROOT).as_posix()
        if copy_one(path, staging / name, log, name, normalize=True):
            docs_count += 1
    log['trees']['docs'] = docs_count

    # 5. Root files and CI metadata. Markdown root files carry historical command
    # records, so they are normalized like docs; code and manifests are not.
    for name in ROOT_FILES:
        source = ROOT / name
        if source.is_file():
            copy_one(source, staging / name, log, name,
                     normalize=source.suffix.lower() == '.md')
        else:
            log['missing'].append(name)
    for tree in EXTRA_TREES:
        base = ROOT / tree
        if base.is_dir():
            for path in walk_files(base):
                relative = path.relative_to(ROOT).as_posix()
                # GitHub rejects a push that creates a workflow file from an OAuth
                # token without the `workflow` scope. The workflow is authored and
                # kept in the working tree; it ships once that scope is granted.
                if relative.startswith('.github/workflows/'):
                    log['not_published'].append(
                        {'path': relative,
                         'reason': 'workflow file requires the gh token `workflow` scope; '
                                   'run `gh auth refresh -h github.com -s workflow` to publish it'})
                    continue
                copy_one(path, staging / relative, log, relative, normalize=False)

    # 6. Curated evidence receipts, normalized except where a frozen registry
    # pins the bytes.
    pinned = registry_pinned_paths()
    log['registry_pinned_byte_exact'] = sorted(pinned)
    seen = set()
    for pattern in EVIDENCE_PATTERNS:
        for path in sorted(ROOT.glob(pattern)):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT).as_posix()
            if relative in seen or any(part in EXCLUDED_DIR_NAMES for part in path.parts):
                continue
            size = path.stat().st_size
            if size > MAX_FILE_MIB * 1024 * 1024:
                log['skipped_oversize'].append({'path': relative, 'mib': round(size / 1024**2, 2)})
                continue
            if (log['bytes'] + size) / 1024**2 > MAX_TOTAL_MIB:
                log['budget_exhausted_at'] = relative
                break
            # Everything published is normalized. The registry-pinned receipts are
            # not shipped at all (see 6b), so no published file needs to stay
            # byte-exact against a frozen pin.
            if copy_one(path, staging / relative, log, relative, normalize=True):
                seen.add(relative)
                log['evidence_files'] += 1

    # 6b. The registry closure is enumerated but deliberately NOT copied. It ends
    # in derived views of a third-party public dataset that is not redistributed,
    # and its receipts are SHA-pinned, so shipping them would either break the
    # chain (if normalized) or publish the producing host's paths (if byte-exact).
    # naheng.data.registry_availability turns this into an explicit external data
    # dependency and the affected tests skip with a reason.
    log['registry_pinned_not_distributed'] = sorted(pinned)
    log['registry_pinned_count'] = len(pinned)
    log['registry_pinned_bytes'] = sum(pinned.values())

    # 7. Runtime directories tests expect to exist (git cannot store empty dirs).
    for runtime_dir in ('artifacts/calibration', 'artifacts/discovery', 'artifacts/test-temp'):
        (staging / runtime_dir).mkdir(parents=True, exist_ok=True)
        (staging / runtime_dir / '.gitkeep').write_text('', encoding='utf-8')

    # 8. Generated concise status, replacing the internal append-only log.
    try:
        import yaml
        ledger = yaml.safe_load((ROOT / 'TASKS.yaml').read_text(encoding='utf-8'))
        rows = ledger['tasks']
        counts = {}
        for row in rows:
            counts[row['status']] = counts.get(row['status'], 0) + 1
        lines = ['# 实施状态概览', '',
                 '本文件是面向读者的状态概览。逐轮真实命令、退出码与首次失败的完整追加日志属于内部工程记录，不随仓库发布。',
                 '', f'任务总数 **{len(rows)}**，需求 **{len(yaml.safe_load((ROOT / "REQUIREMENTS.yaml").read_text(encoding="utf-8"))["requirements"])}** 项，全部保留。',
                 '', '| 状态 | 数量 |', '|---|---|']
        lines += [f'| {status} | {count} |' for status, count in sorted(counts.items())]
        lines += ['', '## 未完成项', '']
        for row in rows:
            if row['status'] != 'done':
                lines.append(f'* **{row["id"]}** ({row["status"]}, {row["milestone"]}) — {row["title"]}')
                if row.get('blocker'):
                    lines.append(f'  * 阻塞：{row["blocker"]}')
        lines += ['', '完整发布门 `verify --profile release` 目前返回退出码 **2**（必需项受阻/未验收）。',
                  '主张与证据边界见 [CLAIMS.md](CLAIMS.md)。', '']
        (staging / 'docs' / 'STATUS_OVERVIEW.md').write_text('\n'.join(lines), encoding='utf-8')
        log['generated'] = ['docs/STATUS_OVERVIEW.md']
    except Exception as error:  # never fail the build on the generated overview
        log['status_overview_error'] = repr(error)

    # 9. Bundle-specific .gitignore.
    (staging / '.gitignore').write_text("""# The working tree ignores artifacts/ wholesale; this repository ships a curated
# evidence subset that must be tracked.
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
frontend/tsconfig.tsbuildinfo
*.egg-info/
data/raw/
configs/discovery/proof-backend-host.json

# Runtime residue created by running the test suite or the CLI in a clone.
# Curated evidence under artifacts/ stays tracked; only generated output is
# ignored. The two directories tests need to exist keep a tracked .gitkeep.
artifacts/test-temp/*
!artifacts/test-temp/.gitkeep
artifacts/discovery/*
!artifacts/discovery/.gitkeep
artifacts/runs/
artifacts/recovery/
artifacts/demo/
artifacts/smoke_demo/
artifacts/calibration/consumer-*/
artifacts/calibration/consumer-test-input-*/
artifacts/calibration/a03-determinism-*/
artifacts/calibration/learning-current-*/
artifacts/calibration/comparison-*/
artifacts/calibration/frontier-*/
artifacts/calibration/diag-probe-*/
.env
.env.*
*.key
*.pem
*.p12
*.pfx
""", encoding='utf-8')

    # 10. Citation check.
    found = {}
    for markdown in sorted(staging.rglob('*.md')):
        text = markdown.read_text(encoding='utf-8', errors='replace')
        where = markdown.relative_to(staging).as_posix()
        for citation in PATH_CITATION.findall(text):
            found.setdefault(citation.rstrip('.,;:)'), set()).add(where)
    resolved, declared, broken = {}, {}, {}
    for citation, sources in sorted(found.items()):
        if (staging / citation).exists():
            resolved[citation] = sorted(sources)
        elif '*' in citation:
            resolved[citation + ' (glob)'] = sorted(sources)
        elif citation in EXPECTED_ABSENT:
            declared[citation] = {'reason': EXPECTED_ABSENT[citation], 'cited_by': sorted(sources)}
        else:
            broken[citation] = sorted(sources)
    readme_broken = {p: s for p, s in broken.items() if 'README.md' in s}

    log.update({'staging': str(staging), 'total_mib': round(log['bytes'] / 1024**2, 2),
                'citations_resolved': len(resolved), 'citations_declared_absent': len(declared),
                'citations_broken': len(broken), 'readme_citations_broken': len(readme_broken)})
    normalization_map = log.pop('normalization_sha256_original')
    (staging / 'NORMALIZATION_SHA256.json').write_text(json.dumps(
        {'purpose': 'SHA256 of each working-tree original whose published copy had machine-specific '
                    'path prefixes rewritten. The transform is prefix substitution only, so a reviewer '
                    'can re-derive any published file from its original.',
         'rules': display_rules(),
         'file_count': len(normalization_map),
         'files': normalization_map}, indent=2, ensure_ascii=False), encoding='utf-8')
    (staging / 'BUNDLE_MANIFEST.json').write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding='utf-8')

    index = ['# 开源包内容与边界', '',
             f'本仓库是工作树的**可审阅、可运行子集**，共 {log["total_mib"]} MiB。',
             f'* 源码/测试/工具/配置/Lean 源/前端源：{log["source_files"]} 个文件',
             f'* 精选证据收据：{log["evidence_files"]} 个文件',
             f'* `tools/` 策展：保留 {log["trees"].get("tools", 0)} 个，排除 {log["tools_excluded"]} 个一次性会话脚本',
             f'* 路径规范化：{log["normalized_files"]} 个文件的本机绝对路径已改写为占位符',
             f'* 引用核对：{len(resolved)} 条可解析，{len(declared)} 条为有意提及的不存在路径，{len(broken)} 条不可解析',
             '', '## 路径规范化规则', '',
             '证据收据记录的是产出它的机器上的绝对路径。发布副本按下列规则改写，**工作树原件从不改写**；',
             '每个被改写文件的原始 SHA256 记录在 `NORMALIZATION_SHA256.json`，因此该变换可审计、可逆向。', '',
             '| 原前缀（账号名已脱敏） | 占位符 |', '|---|---|']
    for row in display_rules():
        index.append(f'| `{row["pattern"]}` | `{row["replacement"]}` |')
    index.append('')
    index.append('权威正则见 `tools/build_publication_bundle.py` 的 `NORMALIZATIONS`；'
                 '本表与清单只作说明，因此不重复发布被移除的标识符本身。')
    index += ['', '## 有意排除', '',
              '* `artifacts/` 批量工件（2.6 GiB）—— 运行轨迹、恢复测试转储、审查工作树',
              '* `formal/.lake/` —— Lean 构建产物；用锁定工具链 `lake build` 重建',
              '* `data/raw/`（303 MiB）—— 第三方公开测量原始 CSV，按其上游许可保留在原处；'
              '`data/manifests/` 提供来源、许可、逐成员 SHA256 与重新获取方式',
              '* `.venv/` `.bootstrap/` `.tools/` —— 解释器、uv 与 Lean 工具链',
              '* `frontend/node_modules/` `frontend/dist/` —— `npm install` 与 `npm run build` 可重建',
              '* `tools/` 中 226 个一次性会话脚本 —— 见上方策展计数',
              '* `docs/STATUS.md`（742 行追加式会话日志）、`START_CODEX.md`、`HANDOFF_CHECK.json` —— 内部工程记录',
              '* `configs/discovery/proof-backend-host.json` —— 本机后端位置；已 gitignore，发布 `.example` 副本',
              '', '## 文档有意提及、但本包内不存在的路径', '']
    for path, row in sorted(declared.items()):
        index.append(f'* `{path}` —— {row["reason"]}')
    index += ['', '## 不可解析的引用', '',
              '这些路径出现在文档中但不在本包内：多数是 `docs/` 中历史检查点里"下一条执行命令"的输出目标'
              '（命令尚未运行，或输出已被后续轮次取代），少数属于被排除的批量工件。全部如实列出。', '']
    for path, sources in sorted(broken.items()):
        index.append(f'* `{path}` —— 被引用于 {", ".join(f"`{s}`" for s in sources[:3])}'
                     + ('' if len(sources) <= 3 else f' 等 {len(sources)} 处'))
    if log['permission_denied']:
        index += ['', '## 因权限未能复制', ''] + [f'* `{r["path"]}`' for r in log['permission_denied'][:40]]
    (staging / 'EVIDENCE_INDEX.md').write_text('\n'.join(index) + '\n', encoding='utf-8')

    # 11. Prove the normalization actually worked, last, so that the generated
    # manifest and index are inside the scanned surface too. Trusting the rules
    # is not enough — an earlier version of this builder scanned before writing
    # them and so missed the identifier they echo back.
    exempt_files, exempt_prefixes = _portability_exemptions()
    residual = []
    byte_exact = []
    for path in sorted(staging.rglob('*')):
        if not path.is_file() or '.git' in path.parts:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        relative = path.relative_to(staging).as_posix()
        if relative in exempt_files or relative.startswith(exempt_prefixes):
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        found = [number for number, line in enumerate(text.splitlines(), 1)
                 if RESIDUAL_HOST_PATH.search(line)]
        if relative in pinned:
            if found:
                byte_exact.append({'path': relative, 'lines': len(found)})
            continue
        for number in found:
            line = text.splitlines()[number - 1]
            residual.append({'path': relative, 'line': number, 'text': line.strip()[:140]})
    scan_report = {
        'scanned_after_all_generated_files': True,
        'residual_host_paths': len(residual),
        'residuals': residual[:50],
        'byte_exact_registry_pinned_files': byte_exact,
        'byte_exact_rationale':
            'These receipts are pinned by SHA256 in data/manifests/sources.yaml and '
            'validate_new_source refuses to run when a byte differs. They are published '
            'unmodified so a reader can verify the frozen data-integration chain; the host '
            'paths inside them are historical provenance records, not configuration.',
        'exempt_files': {name: reason for name, reason in sorted(exempt_files.items())
                         if (staging / name).exists()},
        'exempt_path_prefixes': list(exempt_prefixes),
        'exemption_rationale': 'only the tools that define or apply these patterns, and the '
                               'gitignored host-location config, may name them; the derived '
                               'manifest and index redact the identifier',
        'note': 'this file is written after the scan and contains only counts and '
                'repository-relative paths',
    }
    (staging / 'PORTABILITY_SCAN.json').write_text(json.dumps(scan_report, indent=2, ensure_ascii=False),
                                                   encoding='utf-8')
    with (staging / 'EVIDENCE_INDEX.md').open('a', encoding='utf-8') as stream:
        stream.write('\n## 字节精确发布（冻结登记链要求）\n\n'
                     f'下列 {len(byte_exact)} 个文件被 `data/manifests/sources.yaml` 按 SHA256 钉住，'
                     '因此**原样发布、不做路径规范化**：改写任何一个字节都会让读者无法验证冻结的数据登记链，'
                     '并让数据登记测试失败。它们内部的历史绝对路径属于来源记录，不是配置项。\n\n')
        for row in byte_exact:
            stream.write(f'* `{row["path"]}`（{row["lines"]} 行含本机路径）\n')
        stream.write('\n完整理由与逐文件清单见 `PORTABILITY_SCAN.json`。\n')
    log['residual_host_paths'] = len(residual)
    (staging / 'BUNDLE_MANIFEST.json').write_text(json.dumps(log, indent=2, ensure_ascii=False),
                                                 encoding='utf-8')
    if residual:
        print(json.dumps({'status': 'aborted_residual_host_paths', 'count': len(residual),
                          'first_20': residual[:20]}, indent=2, ensure_ascii=False))
        return 2

    print(json.dumps({k: log[k] for k in ('staging', 'total_mib', 'source_files', 'evidence_files',
                                          'normalized_files', 'residual_host_paths', 'tools_excluded',
                                          'citations_resolved',
                                          'citations_declared_absent', 'citations_broken',
                                          'readme_citations_broken', 'trees',
                                          'allowlisted_tools_absent')}, indent=2, ensure_ascii=False))
    if readme_broken:
        print(json.dumps({'README_broken_citations': sorted(readme_broken)}, indent=2, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
