"""Resolve the explicitly activated foundation manifest without a latest-file guess."""
import json
from pathlib import Path
from naheng.runtime.artifacts import sha256_file


def select_foundation(project: Path):
    project = project.resolve()
    pointer = project / "artifacts/formal/active_foundation.json"
    if not pointer.exists():
        legacy = project / "artifacts/formal/foundation/manifest.json"
        return (legacy if legacy.is_file() else None), "No active pointer; legacy manifest is revalidated individually"
    try:
        value = json.loads(pointer.read_text(encoding="utf-8"))
        name = value["manifest"]
        if not isinstance(name, str) or not name.startswith("artifacts/formal/"):
            raise ValueError("Controlled formal artifact path required")
        path = (project / name).resolve()
        if not path.is_relative_to(project / "artifacts/formal") or sha256_file(path) != value["sha256"]:
            raise ValueError("Active proof manifest is missing or has changed")
        return path, "Explicit active manifest hash verified; declaration import remains mandatory"
    except (ValueError, KeyError, TypeError, OSError) as error:
        return None, "Active proof authority withdrawn: " + str(error)


def select_reduction_residual(project: Path):
    """Explicit selection of the partial instantaneous-rate suite, no fallback."""
    project = project.resolve()
    pointer = project / "artifacts/formal/active_reduction_residual.json"
    if not pointer.is_file():
        return None, "No active instantaneous residual-rate declaration pointer"
    try:
        value = json.loads(pointer.read_text(encoding="utf-8"))
        name = value["manifest"]
        if not isinstance(name, str) or not name.startswith("artifacts/formal/"):
            raise ValueError("Controlled residual artifact path required")
        path = (project / name).resolve()
        if not path.is_relative_to(project / "artifacts/formal") or sha256_file(path) != value["sha256"]:
            raise ValueError("Active residual manifest is missing or has changed")
        return path, "Explicit residual manifest hash verified; typed declaration binding remains mandatory"
    except (ValueError, KeyError, TypeError, OSError) as error:
        return None, "Active residual-rate authority withdrawn: " + str(error)


def select_core(project: Path):
    """Select explicitly activated core metadata; import checks remain mandatory."""
    project = project.resolve()
    pointer = project/'artifacts/formal/active_core.json'
    if not pointer.is_file(): return None, 'No activated complete core publication'
    try:
        value = json.loads(pointer.read_text(encoding='utf-8'))
        name = value['manifest']
        if not isinstance(name, str) or not name.startswith('artifacts/formal/'):
            raise ValueError('Controlled core artifact path required')
        path = (project/name).resolve()
        if not path.is_relative_to(project/'artifacts/formal') or sha256_file(path) != value['sha256']:
            raise ValueError('Activated core manifest is missing or has changed')
        report = json.loads(path.read_text(encoding='utf-8'))
        if report.get('suite') != 'core' or report.get('checked') is not True or report.get('exit_code') != 0:
            raise ValueError('Complete core build and audit unavailable')
        return path, 'Explicit core hash verified; individual source and statement import still required'
    except (ValueError, KeyError, TypeError, OSError) as error:
        return None, 'Core publication withdrawn: '+str(error)
