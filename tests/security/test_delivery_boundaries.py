import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]


def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def test_launcher_accepts_only_loopback_and_no_unknown_credentials():
    launcher=module('delivery_launcher','start_local.py')
    for host in ('127.0.0.1','::1','localhost'):assert launcher.checked_host(host)==host
    for host in ('0.0.0.0','::','example.com','192.168.1.2'):
        with pytest.raises(ValueError):launcher.checked_host(host)
    result=launcher.child_environment(Path('C:/workspace'),{'PATH':'bin','SYSTEMROOT':'C:/Windows','OPENAI_API_KEY':'synthetic-canary','HTTPS_PROXY':'synthetic-credential','PYTHONPATH':'unsafe'})
    assert 'OPENAI_API_KEY' not in result and 'HTTPS_PROXY' not in result and result['PYTHONPATH']==str(Path('C:/workspace')/'src')


def test_delivery_input_excludes_user_history_and_secret_names(tmp_path):
    builder=module('delivery_builder','build_delivery.py')
    for name in ('src/safe.py','configs/a.yaml','configs/.env.private','configs/identity.key','artifacts/runs/old.json'):
        target=tmp_path/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('synthetic control',encoding='utf-8')
    names={p.relative_to(tmp_path).as_posix() for p in builder.source_files(tmp_path)}
    assert names=={'src/safe.py','configs/a.yaml'}


def test_manifest_tamper_and_path_escape_are_rejected(tmp_path):
    launcher=module('delivery_launcher','start_local.py')
    target=tmp_path/'safe.txt';target.write_text('changed',encoding='utf-8')
    for name in ('safe.txt','../outside.txt'):
        (tmp_path/'delivery_manifest.json').write_text(json.dumps({'files':{name:{'sha256':'0'*64}},'source_code_hash':'0'*64}),encoding='utf-8')
        with pytest.raises(ValueError):launcher.verify_delivery(tmp_path.resolve())
