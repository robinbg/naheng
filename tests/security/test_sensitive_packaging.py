import ast,hashlib,importlib.util,json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]

def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

@pytest.fixture
def modules():return load('builder_e','build_delivery.py'),load('launcher_e','start_local.py')

def fixture(tmp_path,builder):
    root=tmp_path/'s';(root/'src').mkdir(parents=True);(root/'src/safe.py').write_text('# synthetic source')
    (root/'uv.lock').write_text('test lock');(root/'frontend/src').mkdir(parents=True)
    (root/'frontend/src/app.ts').write_text('// source');(root/'frontend/package-lock.json').write_text('{}')
    built=tmp_path/'b';built.mkdir();(built/'index.html').write_text('<title>Synthetic build control</title>')
    receipt=tmp_path/'r.json'
    def refresh():receipt.write_text(json.dumps({'scope':'Synthetic byte-integrity control, not actual frontend compilation', 'source_sha256':builder.frontend_hash(root),'native_codes':[0,0],'artifacts':{p.relative_to(built).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in built.rglob('*') if p.is_file()}}))
    refresh();dest=tmp_path/'d'
    args=['--project-root',str(root),'--built-frontend',str(built),'--frontend-receipt',str(receipt),'--destination',str(dest)]
    return root,built,receipt,dest,args,refresh

BAD=['.env','.ENV.local','assets/.env/config.txt','assets/key.pem','assets/key.PFX','assets/.npmrc','assets/.netrc','assets/.aws/credentials','assets/.ssh/id_rsa','node_modules/cache.js','assets/identity.key/safe.txt']

@pytest.mark.parametrize('relative',BAD)
def test_sensitive_built_tree_rejected_before_target(tmp_path,modules,relative):
    builder,_=modules;root,built,receipt,dest,args,refresh=fixture(tmp_path,builder)
    file=built/relative;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('SYNTHETIC_CANARY_NOT_A_SECRET');refresh()
    with pytest.raises(ValueError,match='Forbidden frontend build path'):builder.main(args)
    assert not dest.exists() and not list(tmp_path.glob('.nde-*'))

def test_empty_sensitive_build_directory_is_also_rejected(tmp_path,modules):
    builder,_=modules;root,built,receipt,dest,args,refresh=fixture(tmp_path,builder);(built/'.env').mkdir()
    with pytest.raises(ValueError,match='Forbidden frontend build path'):builder.main(args)
    assert not dest.exists()

@pytest.mark.parametrize('name',['docs/key.pem','frontend/dist/.env','tools/.npmrc','docs/.netrc','docs/.aws/credentials','tools/.ssh/id_rsa','docs/key.pem/safe.txt','../outside.txt','C:/key.txt','docs\\key.pem','docs//file.txt','docs/x.','docs/../file.txt','docs/bad\x00name'])
def test_manifest_sensitive_or_noncanonical_names_rejected_even_with_matching_hash(tmp_path,modules,name):
    _,launcher=modules
    if '\x00' not in name and '\\' not in name and ':' not in name and '..' not in name and '//' not in name:
        file=tmp_path/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('SYNTHETIC_CANARY')
        digest=hashlib.sha256(file.read_bytes()).hexdigest()
    else:digest='0'*64
    (tmp_path/'delivery_manifest.json').write_text(json.dumps({'files':{name:{'sha256':digest}},'source_code_hash':'0'*64}))
    with pytest.raises(ValueError,match='Forbidden delivery manifest path'):launcher.verify_delivery(tmp_path)

@pytest.mark.parametrize('name',['frontend/dist/index.html','frontend/dist/assets/app.js','frontend/dist/assets/app.css','frontend/dist/assets/app.js.map','frontend/dist/assets/font.woff2','frontend/dist/assets/model.wasm','src/naheng/__init__.py','docs/credentials.md'])
def test_legitimate_assets_and_source_remain_permitted(modules,name):
    builder,launcher=modules;assert builder.permitted(name) and launcher.permitted(name)

def test_builder_and_launcher_share_exact_policy_ast(modules):
    builder,launcher=modules
    def body(module):
        tree=ast.parse(Path(module.__file__).read_text());wanted={'EXCLUDED','FORBIDDEN_SUFFIXES','CREDENTIAL_NAMES','CREDENTIAL_DIRECTORIES'}
        return [ast.dump(node,include_attributes=False) for node in tree.body if (isinstance(node,ast.FunctionDef) and node.name=='permitted') or (isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in wanted for t in node.targets))]
    assert body(builder)==body(launcher)

def test_valid_source_and_assets_copy_and_verify(tmp_path,modules):
    builder,launcher=modules;root,built,receipt,dest,args,refresh=fixture(tmp_path,builder)
    for name in ('assets/app.js','assets/app.css','assets/font.woff2'):
        file=built/name;file.parent.mkdir(exist_ok=True);file.write_bytes(b'synthetic compiled asset')
    refresh();builder.main(args)
    assert launcher.verify_delivery(dest)['kind']=='manifested_delivery'
    assert (dest/'src/safe.py').read_bytes()==(root/'src/safe.py').read_bytes()
    assert (dest/'frontend/dist/assets/font.woff2').read_bytes()==(built/'assets/font.woff2').read_bytes()
    assert not list(tmp_path.glob('.nde-*'))

def test_changed_bytes_after_copy_refused_without_target(tmp_path,modules,monkeypatch):
    builder,_=modules;root,built,receipt,dest,args,refresh=fixture(tmp_path,builder)
    original=builder.shutil.copyfile
    def changed(source,target,*a,**kw):
        result=original(source,target,*a,**kw)
        if Path(source)==built/'index.html':Path(target).write_text('injected post-copy difference')
        return result
    monkeypatch.setattr(builder.shutil,'copyfile',changed)
    with pytest.raises(ValueError,match='Frontend changed'):builder.main(args)
    assert not dest.exists() and not list(tmp_path.glob('.nde-*'))

def test_source_change_during_copy_refused_without_target(tmp_path,modules,monkeypatch):
    builder,_=modules;root,built,receipt,dest,args,refresh=fixture(tmp_path,builder)
    original=builder.shutil.copyfile
    def changed(source,target,*a,**kw):
        result=original(source,target,*a,**kw)
        if Path(source)==root/'src/safe.py':Path(source).write_text('# changed during copy')
        return result
    monkeypatch.setattr(builder.shutil,'copyfile',changed)
    with pytest.raises(ValueError,match='Source changed'):builder.main(args)
    assert not dest.exists() and not list(tmp_path.glob('.nde-*'))
