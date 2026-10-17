"""Build an auditable local source delivery without copying user histories."""
from pathlib import Path,PurePath,PurePosixPath
import argparse,hashlib,json,os,shutil,stat,subprocess,sys,tempfile

FOLDERS=('src','configs','formal','model_packages','experiments','tools','docs','tests','frontend/src')
FILES=('pyproject.toml','uv.lock','AGENTS.md','PLANS.md','TASKS.yaml','REQUIREMENTS.yaml',
       'frontend/package.json','frontend/package-lock.json','frontend/tsconfig.json','frontend/vite.config.ts',
       'frontend/index.html','compose.yaml','Dockerfile','.dockerignore',
       'data/synthetic/e02-train-1977f8a08879.json')
EXCLUDED={'artifacts','.git','.venv','.bootstrap','node_modules','.lake','__pycache__','.pytest_cache'}
FORBIDDEN_SUFFIXES={'.pem','.key','.p12','.pfx','.pyc'}
CREDENTIAL_NAMES={'.npmrc','.netrc','_netrc','.pypirc','.git-credentials','id_rsa','id_dsa','id_ecdsa','id_ed25519'}
CREDENTIAL_DIRECTORIES={'.ssh','.aws','.azure','.kube','.docker','.gnupg'}


def permitted(relative):
    if isinstance(relative,PurePath):name=relative.as_posix()
    elif isinstance(relative,str):name=relative
    else:return False
    if not name or any(char in name for char in ('\\',':','\x00')) or name.startswith('/'):
        return False
    parts=name.split('/')
    if any(not part or part in {'.','..'} or part!=part.rstrip(' .') for part in parts):
        return False
    return not any(part.casefold() in EXCLUDED or part.casefold() in CREDENTIAL_NAMES
                   or part.casefold() in CREDENTIAL_DIRECTORIES or part.casefold().startswith('.env')
                   or PurePosixPath(part).suffix.casefold() in FORBIDDEN_SUFFIXES for part in parts)


def is_reparse(path):
    try:attributes=path.lstat()
    except FileNotFoundError:return False
    return path.is_symlink() or bool(getattr(attributes,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400))


def reject_reparse_path(path):
    for item in (path.absolute(),*path.absolute().parents):
        if is_reparse(item):raise ValueError('Reparse path cannot enter a delivery: '+str(item))


def overlay_files(root):
    reject_reparse_path(root);result=[]
    if not root.is_dir():raise ValueError('Overlay directory is missing')
    for current,dirs,files in os.walk(root):
        for name in dirs+files:
            file=Path(current)/name;rel=file.relative_to(root)
            if not permitted(rel):raise ValueError('Forbidden overlay path: '+rel.as_posix())
            if is_reparse(file):raise ValueError('Reparse overlay path: '+rel.as_posix())
            if rel.parts[0] not in {'tools','docs','tests','compose.yaml','Dockerfile','.dockerignore'}:
                raise ValueError('Delivery overlay must only add packaging/documentation/security tests')
            if file.is_file():result.append(file)
    return sorted(result)


def built_files(root):
    reject_reparse_path(root)
    if not root.is_dir():raise ValueError('Frontend build directory is missing')
    result=[]
    for current,dirs,files in os.walk(root):
        for name in dirs+files:
            file=Path(current)/name;relative=file.relative_to(root)
            if not permitted(relative):raise ValueError('Forbidden frontend build path: '+relative.as_posix())
            if is_reparse(file):raise ValueError('Reparse path in frontend build')
            if file.is_file():result.append(file)
    return sorted(result)


def source_files(root):
    reject_reparse_path(root)
    collected=set()
    for folder in FOLDERS:
        start=root/folder
        if not start.is_dir():continue
        if is_reparse(start):raise ValueError('Reparse source root cannot enter a delivery')
        for current,dirs,files in os.walk(start):
            dirs[:]=[x for x in dirs if permitted((Path(current)/x).relative_to(root))]
            if any(is_reparse(Path(current)/x) for x in dirs):raise ValueError('Reparse source directory cannot enter a delivery')
            for name in files:
                p=Path(current)/name
                if not permitted(p.relative_to(root)):continue
                if is_reparse(p):raise ValueError('Reparse source file cannot enter a delivery')
                if p.is_file():collected.add(p)
    for name in FILES:
        if (root/name).is_file():
            reject_reparse_path(root/name);collected.add(root/name)
    return sorted(collected)


def frontend_hash(root):
    files=list((root/'frontend/src').rglob('*'))+[root/'frontend'/name for name in ('package.json','package-lock.json','tsconfig.json','vite.config.ts','index.html')]
    value=hashlib.sha256()
    for file in sorted(p for p in files if p.is_file()):
        value.update(file.relative_to(root).as_posix().encode());value.update(file.read_bytes())
    return value.hexdigest()


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--destination',type=Path,required=True);p.add_argument('--built-frontend',type=Path,required=True);p.add_argument('--frontend-receipt',type=Path,required=True)
    p.add_argument('--overlay',type=Path)
    a=p.parse_args(argv)
    reject_reparse_path(a.project_root);reject_reparse_path(a.built_frontend);reject_reparse_path(a.destination);reject_reparse_path(a.frontend_receipt)
    root=a.project_root.resolve();dest=a.destination.resolve();built=a.built_frontend.resolve()
    if dest.exists():raise ValueError('Destination already exists; refusing to merge or replace')
    if not (built/'index.html').is_file():raise ValueError('Actual built frontend index.html is required')
    compiled=built_files(built)
    sources=source_files(root)
    overlay=overlay_files(a.overlay) if a.overlay else []
    receipt=json.loads(a.frontend_receipt.read_text(encoding='utf-8'))
    if receipt.get('source_sha256')!=frontend_hash(root) or receipt.get('native_codes')!=[0,0]:raise ValueError('Current successful frontend build receipt required')
    actual={p.relative_to(built).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in compiled}
    if actual!=receipt['artifacts']:raise ValueError('Frontend build differs from recorded bytes')
    sys.path.insert(0,str(root/'src'))
    from naheng.runtime.artifacts import code_hash
    before=code_hash(root)
    dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.nde-',dir=dest.parent) as temporary:
        staged=Path(temporary)/'p';staged.mkdir()
        for file in sources:
            reject_reparse_path(file)
            rel=file.relative_to(root);target=staged/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(file,target)
        for file in compiled:
            reject_reparse_path(file)
            relative=file.relative_to(built)
            if not permitted(relative):raise ValueError('Forbidden frontend build path: '+relative.as_posix())
            target=staged/'frontend/dist'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(file,target)
        copied={p.relative_to(staged/'frontend/dist').as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (staged/'frontend/dist').rglob('*') if p.is_file()}
        if copied!=receipt['artifacts']:raise ValueError('Frontend changed during delivery copy')
        shutil.copyfile(a.frontend_receipt,staged/'frontend_build_receipt.json')
        if a.overlay:
            for file in overlay:
                rel=file.relative_to(a.overlay)
                reject_reparse_path(file)
                target=staged/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(file,target)
        if before!=code_hash(root) or before!=code_hash(staged):raise ValueError('Source changed during delivery copy')
        values={file.relative_to(staged).as_posix():{'bytes':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()} for file in sorted(staged.rglob('*')) if file.is_file()}
        if any(not permitted(name) for name in values):raise ValueError('Forbidden staged delivery path')
        model_ids={name:value['sha256'] for name,value in values.items() if name.startswith('model_packages/')}
        manifest={'schema_version':1,'source_code_hash':before,'files':values,'model_package_hashes':model_ids,
            'uv_lock_sha256':values['uv.lock']['sha256'],'frontend_lock_sha256':values['frontend/package-lock.json']['sha256'],
            'frontend_source_sha256':receipt['source_sha256'],
            'included_data_files':[name for name in values if name.startswith('data/')],
            'copied_existing_user_results':False,'dependencies_bundled':False,'formal_proof_objects_bundled':False,
            'data_location':'artifacts/ in the selected project workspace','release_complete':False,
            'scope':'Source plus actual built workbench; clean dependency installation, formal rebuild and full user acceptance remain required'}
        (staged/'delivery_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        if dest.exists():raise ValueError('Destination already exists; refusing to publish')
        os.rename(staged,dest)
    print(json.dumps({'destination':str(dest),'files':len(values),'bytes':sum(x['bytes'] for x in values.values()),'source_code_hash':before,'release_complete':False}))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as error:raise SystemExit(str(error))
