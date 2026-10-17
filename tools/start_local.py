"""Check locked local inputs and start only a loopback workbench by default."""
from pathlib import Path,PurePath,PurePosixPath
import argparse,hashlib,ipaddress,json,os,stat,subprocess,sys


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


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--python',type=Path)
    p.add_argument('--host',default='127.0.0.1')
    p.add_argument('--port',type=int,default=8000)
    p.add_argument('--check-only',action='store_true')
    return p


def checked_host(value):
    if value=='localhost':return value
    try:valid=ipaddress.ip_address(value).is_loopback
    except ValueError:valid=False
    if not valid:raise ValueError('Local launcher accepts loopback addresses only')
    return value


def child_environment(root,environ=None):
    source=os.environ if environ is None else environ
    # No API keys, proxy credentials, tokens or unrelated Python injection.
    allowed={'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','COMSPEC','PATHEXT',
             'USERPROFILE','LOCALAPPDATA','APPDATA','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE'}
    env={key:value for key,value in source.items() if key.upper() in allowed}
    env.update(PYTHONPATH=str(root/'src'),PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1')
    return env


def is_reparse(path):
    try:attributes=path.lstat()
    except FileNotFoundError:return False
    return path.is_symlink() or bool(getattr(attributes,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400))


def reject_reparse_path(path):
    for item in (path.absolute(),*path.absolute().parents):
        if is_reparse(item):raise ValueError('Reparse path cannot supply delivery code: '+str(item))


def verify_delivery(root):
    reject_reparse_path(root)
    manifest=root/'delivery_manifest.json'
    reject_reparse_path(manifest)
    if not manifest.is_file():return {'kind':'source_workspace','manifest':None}
    value=json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(value.get('files'),dict):raise ValueError('Delivery manifest file map is missing')
    for name in value['files']:
        if not permitted(name):raise ValueError('Forbidden delivery manifest path: '+str(name))
    for name,entry in value['files'].items():
        reject_reparse_path(root/name)
        file=(root/name).resolve()
        if not file.is_relative_to(root) or not file.is_file():raise ValueError('Missing or uncontrolled delivery file: '+name)
        if hashlib.sha256(file.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Delivery file changed: '+name)
    immutable=('src','configs','formal','model_packages','experiments','frontend/src','frontend/dist','tools')
    for folder in immutable:
        for file in (root/folder).rglob('*'):
            if is_reparse(file):raise ValueError('Reparse path in immutable delivery source')
            if '__pycache__' in file.parts:continue
            if file.is_file() and file.relative_to(root).as_posix() not in value['files']:
                raise ValueError('Unlisted immutable delivery file: '+file.relative_to(root).as_posix())
    return {'kind':'manifested_delivery','manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
            'source_code_hash':value['source_code_hash'],'copied_existing_user_results':False}


def command(root,python,host,port):
    return [str(python),'-m','naheng.cli','serve','--host',checked_host(host),'--port',str(port)]


def main(argv=None):
    args=parser().parse_args(argv);reject_reparse_path(args.project_root);root=args.project_root.resolve();host=checked_host(args.host)
    if not 1<=args.port<=65535:raise ValueError('TCP port must be in [1,65535]')
    python=(args.python or root/('.venv/Scripts/python.exe' if os.name=='nt' else '.venv/bin/python')).resolve()
    if not python.is_file():raise ValueError('Project interpreter missing. Provision with uv sync --frozen --extra dev --extra reference first.')
    if not (root/'frontend/dist/index.html').is_file():raise ValueError('Actual frontend build missing. Run npm --prefix frontend run build before launch.')
    identity=verify_delivery(root);env=child_environment(root)
    preflight='from pathlib import Path; import json; from naheng.runtime.execution_environment import capture_environment; print(json.dumps(capture_environment(Path('+repr(str(root))+'))))'
    result=subprocess.run([str(python),'-c',preflight],cwd=root,env=env,capture_output=True,text=True,timeout=30)
    if result.returncode:raise ValueError('Dependency preflight failed: '+result.stderr.strip())
    locked=json.loads(result.stdout)
    info={'project_root':str(root),'data_root':str(root/'artifacts'),'host':host,'port':args.port,'hardware_writes':False,
          'identity':identity,'dependencies':locked,'external_model_credentials_forwarded':False,
          'scope':'Local startup readiness only; not complete scientific or product acceptance'}
    print(json.dumps(info,ensure_ascii=False),flush=True)
    if args.check_only:return 0
    child=subprocess.Popen(command(root,python,host,args.port),cwd=root,env=env)
    try:return child.wait()
    except KeyboardInterrupt:
        child.terminate()
        try:return child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();return child.wait(timeout=10)


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,subprocess.SubprocessError) as error:raise SystemExit(str(error))
