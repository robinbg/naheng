import hashlib
import json
from pathlib import Path

from naheng.runtime import artifacts
from naheng.runtime.freezing import freeze_source


def legacy_source_files(root):
    return [
        path
        for folder in ("src", "configs", "formal", "frontend/src", "model_packages")
        for path in sorted((root / folder).rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and ".lake" not in path.parts
    ]


def legacy_code_hash(root, files):
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def make_project(root):
    contents = {
        "src/z.py": "last source",
        "src/a/sub.py": "nested source",
        "src/a.py": "sibling source",
        "src/aa.py": "other sibling source",
        "configs/default.yaml": "execution settings",
        "formal/Naheng/Main.lean": "theorem source",
        "frontend/src/app.ts": "frontend source",
        "model_packages/base/package.json": '{"model":"base"}',
        "formal/.lake/packages/mathlib/Mathlib/Dependency.lean": "dependency excluded",
        "formal/Naheng/__pycache__/cached.pyc": "cache excluded",
        "src/nested/.lake/dependency.txt": "nested dependency excluded",
        "src/__pycache__/cached.pyc": "source cache excluded",
        "configs/.lake": "excluded name even when a file",
        "pyproject.toml": "project lock input",
        "uv.lock": "python dependency lock",
        "frontend/package.json": "frontend package input",
        "frontend/package-lock.json": "frontend dependency lock",
    }
    for relative, content in contents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return contents


def test_source_iterator_preserves_legacy_files_order_and_hash(tmp_path):
    project = tmp_path / "project"
    make_project(project)
    previous_files = legacy_source_files(project)
    assert list(artifacts.iter_source_files(project)) == previous_files
    previous_hash = legacy_code_hash(project, previous_files)
    assert artifacts.code_hash(project) == previous_hash

    snapshot, digest = freeze_source(project, tmp_path / "run")
    assert digest == previous_hash
    assert list(artifacts.iter_source_files(snapshot)) == [
        snapshot / path.relative_to(project) for path in previous_files
    ]
    lock_files = {"pyproject.toml", "uv.lock", "frontend/package.json", "frontend/package-lock.json"}
    expected = {path.relative_to(project).as_posix() for path in previous_files} | lock_files
    source_index = json.loads((tmp_path / "run/source_index.json").read_text(encoding="utf-8"))
    assert set(source_index["files"]) == expected
    for relative, recorded_hash in source_index["files"].items():
        assert recorded_hash == hashlib.sha256((project / relative).read_bytes()).hexdigest()


def test_hash_and_snapshot_do_not_enter_excluded_trees(tmp_path, monkeypatch):
    project = tmp_path / "project"
    make_project(project)
    expected_hash = legacy_code_hash(project, legacy_source_files(project))
    original_scandir = artifacts.os.scandir
    entered = []

    def guarded_scandir(path):
        visited = Path(path)
        assert not {".lake", "__pycache__"}.intersection(visited.parts), visited
        entered.append(visited)
        return original_scandir(path)

    with monkeypatch.context() as guarded:
        guarded.setattr(artifacts.os, "scandir", guarded_scandir)
        assert artifacts.code_hash(project) == expected_hash
        snapshot, digest = freeze_source(project, tmp_path / "run")
        assert digest == expected_hash
        assert artifacts.code_hash(snapshot) == expected_hash
    assert project / "formal" in entered
    assert project / "formal/Naheng" in entered
    assert project / "src/nested" in entered


def test_missing_source_folders_and_excluded_ancestor(tmp_path):
    assert list(artifacts.iter_source_files(tmp_path / "missing")) == []
    project = tmp_path / ".lake" / "project"
    make_project(project)
    assert legacy_source_files(project) == []
    assert list(artifacts.iter_source_files(project)) == []
    assert artifacts.code_hash(project) == hashlib.sha256().hexdigest()
