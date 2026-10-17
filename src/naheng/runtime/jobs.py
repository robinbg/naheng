from __future__ import annotations
import datetime, hashlib, json, sqlite3, uuid
from pathlib import Path
from .artifacts import atomic_json

TERMINAL={"succeeded","failed","cancelled","interrupted"}
_TRANSITIONS={
    "queued":{"queued","running","failed","cancelled","interrupted"},
    "running":{"running","succeeded","failed","cancelled","interrupted"},
}


class JobQuotaExceeded(ValueError):
    """A computation admission limit was reached inside the enqueue transaction."""


class JobStore:
    def __init__(self, root: Path):
        self.root=Path(root)
        self.root.mkdir(parents=True,exist_ok=True)
        self.db=self.root/"jobs.sqlite3"
        with self.connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS jobs (run_id TEXT PRIMARY KEY, state TEXT, config TEXT, input_hash TEXT, progress REAL, error TEXT, updated TEXT, reused_from TEXT, cancel INTEGER DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, payload TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS job_owners (run_id TEXT PRIMARY KEY, identity TEXT NOT NULL)")

    def connect(self):
        c=sqlite3.connect(self.db,timeout=30)
        c.row_factory=sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    @staticmethod
    def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()

    @staticmethod
    def _row(c,run_id):
        row=c.execute("SELECT * FROM jobs WHERE run_id=?",(run_id,)).fetchone()
        if row is None: raise KeyError(run_id)
        result=dict(row);result["config"]=json.loads(result["config"])
        return result

    def _event(self,c,run_id,payload):
        c.execute("INSERT INTO events(run_id,payload) VALUES (?,?)",
                  (run_id,json.dumps({**payload,"utc":self.now()},ensure_ascii=False)))

    def create(self,config:dict,reuse=False,max_nonterminal=None,owner_pid=None)->dict:
        if max_nonterminal is not None and (
            not isinstance(max_nonterminal,int) or isinstance(max_nonterminal,bool) or max_nonterminal<0):
            raise ValueError("Nonterminal quota must be a nonnegative integer or None")
        frozen=json.dumps(config,sort_keys=True,allow_nan=False)
        h=hashlib.sha256(frozen.encode()).hexdigest()
        reused=None
        run_id="nh-"+uuid.uuid4().hex
        if owner_pid is not None:
            from .process_identity import capture_process_identity
            owner=capture_process_identity(owner_pid)
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if max_nonterminal is not None:
                placeholders=",".join("?" for _ in TERMINAL)
                active=c.execute("SELECT COUNT(*) FROM jobs WHERE state NOT IN ("+placeholders+")",
                                 tuple(sorted(TERMINAL))).fetchone()[0]
                if active>=max_nonterminal:
                    raise JobQuotaExceeded("Local worker quota reached")
            if reuse:
                old=c.execute("SELECT run_id FROM jobs WHERE input_hash=? AND state='succeeded' ORDER BY updated DESC LIMIT 1",(h,)).fetchone()
                reused=old["run_id"] if old else None
            c.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)",
                      (run_id,"queued",frozen,h,0,None,self.now(),reused,0))
            if owner_pid is not None:
                c.execute("INSERT INTO job_owners VALUES (?,?)",(run_id,json.dumps(owner)))
            self._event(c,run_id,{"type":"queued","reused_from":reused})
            if owner_pid is not None:
                self._event(c,run_id,{"type":"owner_claimed","phase":"queued","process_identity":owner})
        return self.get(run_id)

    def get(self,run_id):
        with self.connect() as c: return self._row(c,run_id)

    def bind_frozen_config(self,run_id,config):
        canonical={k:v for k,v in config.items() if k!="source_dir"}
        h=hashlib.sha256(json.dumps(canonical,sort_keys=True,allow_nan=False).encode()).hexdigest()
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old=self._row(c,run_id)
            if old["state"]!="queued" or old["cancel"]:
                raise ValueError("Frozen input may only bind to a queued, uncancelled job")
            c.execute("UPDATE jobs SET config=?,input_hash=? WHERE run_id=?",
                      (json.dumps(config,sort_keys=True,allow_nan=False),h,run_id))

    def list(self):
        with self.connect() as c:
            ids=[row["run_id"] for row in c.execute("SELECT run_id FROM jobs ORDER BY updated DESC LIMIT 100").fetchall()]
        return [self.get(run_id) for run_id in ids]

    def count_nonterminal(self):
        placeholders=",".join("?" for _ in TERMINAL)
        with self.connect() as c:
            return c.execute("SELECT COUNT(*) FROM jobs WHERE state NOT IN ("+placeholders+")",
                             tuple(sorted(TERMINAL))).fetchone()[0]

    def try_start(self,run_id,owner_pid=None)->bool:
        """Acquire queued work exactly once, with the running event committed together."""
        if owner_pid is not None:
            from .process_identity import capture_process_identity
            owner=capture_process_identity(owner_pid)
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old=self._row(c,run_id)
            if old["state"]!="queued" or old["cancel"]:
                return False
            cursor=c.execute("UPDATE jobs SET state='running',progress=0,error=NULL,updated=? WHERE run_id=? AND state='queued' AND cancel=0",
                             (self.now(),run_id))
            if cursor.rowcount!=1: return False
            if owner_pid is not None:
                c.execute("INSERT OR REPLACE INTO job_owners VALUES (?,?)",(run_id,json.dumps(owner)))
                self._event(c,run_id,{"type":"owner_claimed","phase":"worker_started","process_identity":owner})
            self._event(c,run_id,{"type":"running","progress":0,"error":None})
        return True

    def bind_worker_owner(self,run_id,pid):
        """Transfer local launch ownership, including workers from old snapshots."""
        from .process_identity import capture_process_identity
        owner=capture_process_identity(pid)
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if self._row(c,run_id)['state'] in TERMINAL: return False
            c.execute("INSERT OR REPLACE INTO job_owners VALUES (?,?)",(run_id,json.dumps(owner)))
            self._event(c,run_id,{"type":"owner_claimed","phase":"dispatched","process_identity":owner})
        return True

    def state(self,run_id,state,progress=None,error=None):
        if state not in TERMINAL|{"queued","running"}: raise ValueError(state)
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old=self._row(c,run_id)
            if old["state"] in TERMINAL:
                if old["state"]!=state:
                    raise ValueError("Terminal job cannot silently restart; create explicit recovery run")
                return
            if state not in _TRANSITIONS.get(old["state"],set()):
                raise ValueError("Invalid job transition")
            if state=="running" and old["state"]=="queued" and old["cancel"]:
                raise ValueError("Cancelled queued work cannot start")
            if state=="succeeded" and old["cancel"]:
                raise ValueError("Cancelled work cannot publish success")
            c.execute("UPDATE jobs SET state=?,progress=?,error=?,updated=? WHERE run_id=?",
                      (state,old["progress"] if progress is None else progress,error,self.now(),run_id))
            self._event(c,run_id,{"type":state,"progress":progress,"error":error})

    def event(self,run_id,payload):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            self._row(c,run_id)
            self._event(c,run_id,payload)

    def events(self,run_id,after=0):
        self.get(run_id)
        with self.connect() as c:
            rows=c.execute("SELECT * FROM events WHERE run_id=? AND sequence>? ORDER BY sequence",(run_id,after)).fetchall()
        return [{"sequence":r["sequence"],**json.loads(r["payload"])} for r in rows]

    def cancel(self,run_id):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old=self._row(c,run_id)
            if old["state"] in TERMINAL: return old
            if not old["cancel"]:
                c.execute("UPDATE jobs SET cancel=1,updated=? WHERE run_id=?",(self.now(),run_id))
                self._event(c,run_id,{"type":"cancel_requested"})
            if old["state"]=="queued":
                c.execute("UPDATE jobs SET state='cancelled',updated=? WHERE run_id=?",(self.now(),run_id))
                self._event(c,run_id,{"type":"cancelled","progress":old["progress"],"error":None})
        return self.get(run_id)

    def recover_interrupted(self):
        """Recover dead/unowned jobs; preserve live or unobservable exact owners.

        Process birth identity prevents PID reuse from becoming live authority.
        Legacy rows without ownership keep the existing incomplete recovery
        policy. Unobservable ownership defers recovery rather than cancelling
        a possibly live computation.
        """
        from .process_identity import process_identity_alive
        recovered=0
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            rows=c.execute("SELECT jobs.run_id,progress,job_owners.identity FROM jobs LEFT JOIN job_owners ON jobs.run_id=job_owners.run_id WHERE state IN ('queued','running')").fetchall()
            for row in rows:
                if row['identity'] is not None:
                    try: identity=json.loads(row['identity'])
                    except (ValueError,TypeError): continue
                    if process_identity_alive(identity) is not False: continue
                reason="Server startup recovery; abandoned work is interrupted, not a complete trajectory"
                c.execute("UPDATE jobs SET state='interrupted',error=?,updated=? WHERE run_id=?",
                          (reason,self.now(),row["run_id"]))
                self._event(c,row["run_id"],{"type":"interrupted","progress":row["progress"],"error":reason})
                recovered+=1
        return recovered

    def checkpoint(self,run_id,payload):
        atomic_json(self.root/run_id/"checkpoint.json",payload)
