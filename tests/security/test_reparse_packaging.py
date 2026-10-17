import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def junction(target,link):
    if os.name=='nt':
        import _winapi
        _winapi.CreateJunction(str(target),str(link))
    else:link.symlink_to(target,target_is_directory=True)


@pytest.mark.parametrize('relative',['tools/.env','tools/.ENV.local','docs/key.key','tools/identity.pem','tests/.bootstrap/file.txt'])
def test_sensitive_overlay_rejected_before_copy(tmp_path,relative):
    builder=load('checked_builder','build_delivery.py');overlay=tmp_path/'overlay';file=overlay/relative
    file.parent.mkdir(parents=True);file.write_text('synthetic canary',encoding='utf-8')
    with pytest.raises(ValueError,match='Forbidden overlay path'):builder.overlay_files(overlay)
    assert list(tmp_path.iterdir())==[overlay]


def test_real_reparse_overlay_and_source_rejected_but_cache_pruned(tmp_path):
    builder=load('checked_builder','build_delivery.py');target=tmp_path/'target';target.mkdir();(target/'file').write_text('synthetic owned target')
    overlay=tmp_path/'overlay';(overlay/'tools').mkdir(parents=True);junction(target,overlay/'tools/link')
    assert builder.is_reparse(overlay/'tools/link')
    with pytest.raises(ValueError,match='Reparse'):builder.overlay_files(overlay)
    source=tmp_path/'source';(source/'src').mkdir(parents=True);safe=source/'src/safe.py';safe.write_text('# synthetic control')
    junction(target,source/'src/__pycache__')
    assert builder.source_files(source)==[safe]
    junction(target,source/'src/included')
    with pytest.raises(ValueError,match='Reparse'):builder.source_files(source)


def test_manifest_cannot_follow_internal_junction(tmp_path):
    launcher=load('checked_launcher','start_local.py');root=tmp_path/'delivery';(root/'src').mkdir(parents=True);(root/'inside').mkdir()
    file=root/'inside/value.txt';file.write_text('synthetic control');junction(root/'inside',root/'src/link')
    (root/'delivery_manifest.json').write_text(json.dumps({'files':{'src/link/value.txt':{'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}},'source_code_hash':'0'*64}),encoding='utf-8')
    with pytest.raises(ValueError,match='Reparse'):launcher.verify_delivery(root)


def test_existing_destination_never_overwritten(tmp_path):
    builder=load('checked_builder','build_delivery.py');dest=tmp_path/'existing';dest.mkdir();sentinel=dest/'sentinel';sentinel.write_text('unchanged')
    with pytest.raises(ValueError,match='Destination already exists'):
        builder.main(['--project-root',str(tmp_path),'--destination',str(dest),'--built-frontend',str(tmp_path/'none'),'--frontend-receipt',str(tmp_path/'none.json')])
    assert sentinel.read_text()=='unchanged' and not (dest/'delivery_manifest.json').exists()
