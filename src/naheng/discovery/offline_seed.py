"""Construct one immutable offline seed from an already regenerated typed batch.

Requires the optional, host-specific isolated proof backend, whose location is
declared by the operator (see naheng.discovery.backend_host). Importing this
module never touches that backend; calling prepare() raises BackendUnavailable
with an actionable message when it is not declared or not present.
"""
import base64
import hashlib
import io
import json
from pathlib import Path
import secrets
import sys
import uuid

from .backend_host import backend_root, maintenance_root

ROOT = Path(__file__).resolve().parents[3]
H = ROOT / 'artifacts/handoff/a02-delegated-backend-20261016-a'
# Relative to the declared maintenance root; never an absolute host path.
PYCDLIB_WHEEL = 'a02-pycdlib-20261016-a/pycdlib-1.14.0-py2.py3-none-any.whl'
BUBBLEWRAP_DEB = ('a02-linux-prepared-rootfs-20261015-b/runs/prepare-130654-1e67dc4f/'
                  'bubblewrap_0.9.0-1ubuntu0.3_amd64.deb')
SOURCES = {'serial_frames_v1.py':'serial_frames_v1.py', 'guest_diagnostic.py': 'guest_diagnostic_r3.py', 'guest_bootstrap.py': 'guest_workload_bootstrap_serial_r2.py',
    'guest_backend.py': 'guest_backend.py', 'guest_sandbox_probe.py': 'guest_sandbox_probe.py',
    'backend_contract.py': 'backend_contract.py', 'guest_profile_setup.py': 'guest_profile_setup.py',
    'guest_workload.py': 'guest_batch_workload.py', 'guest_prepare_runtime.py': 'guest_prepare_runtime.py',
    'guest_batch_job.py': 'guest_batch_job.py', 'guest_batch_probe.py': 'guest_batch_probe_r3.py',
    'guest_batch_delegate.py': 'guest_batch_delegate_r3.py', 'bounded_zstd.py': 'bounded_zstd.py'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source, targets, timeout_s):
    owner = backend_root()
    maintenance = maintenance_root()
    sys.path.insert(0, str(H))
    from ranged_dependency_fetch import safe
    wheel = maintenance / PYCDLIB_WHEEL
    deb = maintenance / BUBBLEWRAP_DEB
    assert sha(wheel) == 'a905827335f0066af3fd416c5cf9b1f29dffaf4d0914b714555213d1809f38d4'
    assert sha(deb) == '2461f1beee9cb04c8942739fe1a2b37e7b7c2a3d518f0779dc75f9245baa3094'
    sys.path.insert(0, str(wheel))
    import pycdlib
    import yaml
    out = owner / ('batch-seed-' + uuid.uuid4().hex[:12]); safe(out); out.mkdir(exist_ok=False)
    identity = {'uuid': '5ba609d1-4988-492f-99d7-0719d006b061', 'nonce': secrets.token_hex(32),
        'guest_code_scope': 'one host-regenerated typed candidate batch; private original-test integration only',
        'dependency_blobs': json.loads((owner / 'blob-views-e981b0ecd391/result.json').read_text(encoding='utf-8'))['blobs'],
        'proof_sources': {'candidate': {'sha256': sha(source)}},
        'batch': {'targets': targets, 'timeout_s': timeout_s}}
    guest = '/opt/naheng-a02-20261016-a/'
    unit = (H / 'naheng-a02-20261016.service').read_text().replace('ConditionVirtualization=qemu', 'ConditionVirtualization=yes')
    unit = unit.replace('guest_backend.py --canary', 'guest_workload.py --canary').replace('TimeoutStartSec=120', 'TimeoutStartSec=1000')
    files = {guest + name: (H / path).read_text(encoding='utf-8') for name, path in SOURCES.items()}
    profile = H / 'apparmor-bwrap-upstream-v4.0.1.profile'
    assert sha(profile) == '11d39094f044f0cda0febb3ad517b830301da6b2ce929664af09ee9e4dd264f9'
    files.update({guest + 'bwrap-upstream.profile': profile.read_text(), guest + 'candidate.lean': source.read_text(encoding='utf-8'),
                  guest + 'boot-inputs.json': json.dumps(identity), '/etc/systemd/system/naheng-a02-20261016.service': unit})
    entries = [{'path': path, 'content': content, 'permissions': '0600'} for path, content in files.items()]
    entries.append({'path': guest + 'bubblewrap.deb', 'content': base64.b64encode(deb.read_bytes()).decode(), 'encoding': 'b64', 'permissions': '0600'})
    config = {'users': [], 'ssh_pwauth': False, 'disable_root': True, 'ssh_deletekeys': True, 'ssh_genkeytypes': ['ed25519'],
              'write_files': entries, 'runcmd': [['/usr/bin/python3', '-I', '-S', guest + 'guest_bootstrap.py'], ['systemctl', 'poweroff']]}
    members = {'user-data': '#cloud-config\n' + yaml.safe_dump(config, sort_keys=False),
        'meta-data': yaml.safe_dump({'instance-id': 'naheng-a02-' + out.name, 'local-hostname': 'naheng-a02-private'}),
        'network-config': 'version: 2\nethernets: {}\n'}
    iso = pycdlib.PyCdlib(); iso.new(interchange_level=3, vol_ident='CIDATA', rock_ridge='1.09', joliet=3)
    for index, (name, text) in enumerate(members.items()):
        raw = text.encode(); (out / name).write_bytes(raw)
        iso.add_fp(io.BytesIO(raw), len(raw), iso_path='/ITEM' + str(index) + ';1', rr_name=name, joliet_path='/' + name)
    target = out / 'seed.iso'; iso.write(str(target)); iso.close()
    reader = pycdlib.PyCdlib(); reader.open(str(target))
    for name, text in members.items():
        check = io.BytesIO(); reader.get_file_from_iso_fp(check, rr_path='/' + name); assert check.getvalue() == text.encode()
    reader.close()
    result = {'exit_code': 0, 'seed': str(target), 'sha256': sha(target), 'readback_exact': True, 'identity': identity,
              'guest_source_sha256': {name: sha(H / name) for name in SOURCES.values()}, 'A02_complete': False}
    plan = out / 'plan.json'; plan.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return plan, result['sha256']
