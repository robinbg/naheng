from __future__ import annotations
import importlib.metadata as md, importlib.util, os, platform, shutil, subprocess, sys
from pathlib import Path
from .artifacts import atomic_json

def doctor(out: Path | None=None):
    versions={}
    for package in ("numpy","scipy","pydantic","fastapi","uvicorn","pytest","PyYAML","pyarrow","pybamm"):
        try: versions[package]={"status":"available","version":md.version(package)}
        except md.PackageNotFoundError: versions[package]={"status":"missing","version":None}
    tools={}
    for name in ("git","node","npm","lean","lake","docker","uv"):
        exe=shutil.which(name)
        if name in {"lean","lake"}:
            project=Path(__file__).resolve().parents[3]
            local=project/".tools/lean/bin"/(name+".exe" if sys.platform=="win32" else name)
            if local.is_file(): exe=str(local)
        if name=="uv" and not exe:
            local=Path.cwd()/".bootstrap/bin/uv.exe"; exe=str(local) if local.is_file() else None
        if not exe: tools[name]={"status":"missing","path":None}; continue
        try:
            args=[exe,"--version"]
            if name=="npm" and sys.platform=="win32": args=["cmd.exe","/d","/c",exe,"--version"]
            r=subprocess.run(args,capture_output=True,timeout=8)
            tools[name]={"status":"available" if r.returncode==0 else "blocked","path":exe,"version":r.stdout.decode(errors="replace").strip(),"exit_code":r.returncode}
        except (subprocess.TimeoutExpired,OSError) as e: tools[name]={"status":"blocked","path":exe,"reason":type(e).__name__}
    result={"python":{"executable":sys.executable,"version":platform.python_version()},"system":platform.platform(),"logical_cores":os.cpu_count(),"workers":max(1,min(4,(os.cpu_count() or 1)//2)),"packages":versions,"tools":tools,"permissions":{"external_llm":False,"paid_compute":False,"publish":False,"hardware_control":False},"scope":"environment_only","exit_code":2 if versions["pybamm"]["status"]!="available" or tools["lake"]["status"]!="available" else 0}
    if out: atomic_json(out,result)
    return result
