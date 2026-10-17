"""Run a command with exact argv, exit code, duration and immutable logs."""
import argparse, datetime, json, subprocess, time, uuid, sys, os, signal
from pathlib import Path

def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    p = argparse.ArgumentParser()
    p.add_argument("--label", required=True)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args()
    argv = a.command[1:] if a.command[:1] == ["--"] else a.command
    root = Path(__file__).resolve().parents[1]
    dest = root/"artifacts"/"validation"/(a.label+"-"+uuid.uuid4().hex[:8])
    dest.mkdir(parents=True)
    started = time.monotonic()
    record = {"argv":argv,"cwd":str(root),"exit_code":None,
              "timeout_s":a.timeout,"status":"started",
              "utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "stdout":str(dest/"stdout.log"),"stderr":str(dest/"stderr.log")}
    # Logs exist and grow during execution, including an interrupted caller.
    with (dest/"stdout.log").open("wb") as out, (dest/"stderr.log").open("wb") as err:
        try:
            proc = subprocess.Popen(argv,cwd=root,stdout=out,stderr=err,
                start_new_session=os.name != "nt",
                env={**os.environ,"PYTHONIOENCODING":"utf-8","PYTHONPATH":str(root/"src")})
            record["owned_pid"] = proc.pid
            (dest/"started.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
            try:
                code = proc.wait(timeout=a.timeout)
                record["timed_out"] = False
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    killed = subprocess.run(["taskkill.exe","/PID",str(proc.pid),"/T","/F"],capture_output=True)
                    (dest/"timeout_kill.log").write_bytes(killed.stdout+killed.stderr)
                    record["kill_exit_code"] = killed.returncode
                else:
                    os.killpg(proc.pid,signal.SIGKILL)
                proc.wait(timeout=30)
                code = 2
                record["timed_out"] = True
                err.write(b"\nTIMEOUT: validation incomplete\n")
        except OSError as e:
            code = 2
            err.write(str(e).encode())
    stdout = (dest/"stdout.log").read_bytes()
    stderr = (dest/"stderr.log").read_bytes()
    record.update(exit_code=code,wall_s=time.monotonic()-started,status="completed")
    (dest/"command.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
    print(stdout.decode("utf-8",errors="replace")[-6000:])
    print(stderr.decode("utf-8",errors="replace")[-2000:])
    print(json.dumps(record,ensure_ascii=False))
    return code
if __name__ == "__main__":
    raise SystemExit(main())
