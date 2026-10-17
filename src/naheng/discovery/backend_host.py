"""Location of the optional, host-specific isolated proof backend.

The backend that runs candidate proofs inside a resource-limited, network-
isolated guest (QEMU plus an offline Linux rootfs plus a pinned Lean toolchain)
is several GiB of machine-specific images. It is deliberately **not** part of
this repository, so its location must be declared by whoever operates it and
must never be hardcoded in source.

Resolution order:

1. the ``NAHENG_PROOF_BACKEND_ROOT`` / ``NAHENG_PROOF_MAINTENANCE_ROOT``
   environment variables;
2. ``configs/discovery/proof-backend-host.json`` with the keys ``backend_root``
   and ``maintenance_root``;
3. otherwise the backend is *unavailable*.

Unavailability is an explicit, actionable condition rather than a crash: no
proof is claimed, nothing is silently skipped, and callers report the reason.
Tests that genuinely need the backend skip with that reason, which keeps the
distinction between "not run here" and "passed" intact.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .grammar import CandidateError

ROOT = Path(__file__).resolve().parents[3]
HOST_CONFIG = ROOT / 'configs' / 'discovery' / 'proof-backend-host.json'

BACKEND_ENV = 'NAHENG_PROOF_BACKEND_ROOT'
MAINTENANCE_ENV = 'NAHENG_PROOF_MAINTENANCE_ROOT'

_INSTALL_HINT = (
    'The isolated native proof backend is host-specific and is not bundled with '
    'this repository. Declare its location with {env}=<absolute path> or in '
    '{config}. See docs/PROOF_BACKEND.md. Without it, candidate proofs are '
    'reported as unavailable and are never claimed as checked.'
)


class BackendUnavailable(CandidateError):
    """The optional isolated proof backend is not declared or not present."""


def install_hint() -> str:
    """One actionable sentence explaining how to declare the backend."""
    return _INSTALL_HINT.format(env=BACKEND_ENV, config=HOST_CONFIG.name)


def _host_config() -> dict:
    if not HOST_CONFIG.is_file():
        return {}
    try:
        loaded = json.loads(HOST_CONFIG.read_text(encoding='utf-8'))
    except (ValueError, OSError) as error:
        raise BackendUnavailable(f'{HOST_CONFIG.name} is not readable JSON: {error!r}') from error
    if not isinstance(loaded, dict):
        raise BackendUnavailable(f'{HOST_CONFIG.name} must contain a JSON object')
    return loaded


def _declared(kind: str, env_name: str, config_key: str) -> Path | None:
    value = os.environ.get(env_name) or _host_config().get(config_key)
    if not value:
        return None
    path = Path(str(value))
    if not path.is_absolute():
        raise BackendUnavailable(
            f'{kind} must be an absolute path; got {str(value)!r} from {env_name}/{config_key}')
    return path


def backend_root() -> Path:
    """Absolute root of the isolated proof backend, or raise BackendUnavailable."""
    path = _declared('backend_root', BACKEND_ENV, 'backend_root')
    if path is None:
        raise BackendUnavailable(_INSTALL_HINT.format(env=BACKEND_ENV, config=HOST_CONFIG.name))
    if not path.is_dir():
        raise BackendUnavailable(f'Declared backend_root does not exist: {path}')
    return path


def maintenance_root() -> Path:
    """Absolute root of prepared backend dependencies, or raise BackendUnavailable."""
    path = _declared('maintenance_root', MAINTENANCE_ENV, 'maintenance_root')
    if path is None:
        raise BackendUnavailable(_INSTALL_HINT.format(env=MAINTENANCE_ENV, config=HOST_CONFIG.name))
    if not path.is_dir():
        raise BackendUnavailable(f'Declared maintenance_root does not exist: {path}')
    return path


def backend_available() -> bool:
    """True only when both declared roots exist. Never raises."""
    try:
        backend_root()
        maintenance_root()
    except (BackendUnavailable, OSError):
        return False
    return True


def availability_report() -> dict:
    """Self-describing status for doctor output and test skip reasons."""
    try:
        backend, maintenance = backend_root(), maintenance_root()
        return {'available': True, 'backend_root': str(backend),
                'maintenance_root': str(maintenance), 'source': 'declared'}
    except BackendUnavailable as error:
        return {'available': False, 'backend_root': None, 'maintenance_root': None,
                'reason': str(error)}
