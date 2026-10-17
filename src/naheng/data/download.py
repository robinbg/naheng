"""Bounded read-only audit/download of the allowlisted RWTH sodium dataset."""
from __future__ import annotations
import argparse
import base64
import subprocess
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile

SOURCE_ID = "rwth_sodium_gassing_987579"
RECORD_URL = "https://publications.rwth-aachen.de/record/987579"
ZIP_NAME = "Data_Failure_Mode_and_Degradation_Analysis_of_a_Commercial_Sodium-Ion_Battery_With_Severe_Gassing_Issue.zip"
ZIP_URL = RECORD_URL + "/files/" + ZIP_NAME
BUDGET_BYTES = 100 * 1024 * 1024


def allowed_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "publications.rwth-aachen.de":
        raise ValueError("Download host is outside the source allowlist")
    if parsed.username or parsed.password or not (parsed.path == "/record/987579" or parsed.path.startswith("/record/987579/")):
        raise ValueError("Unapproved record or credential-bearing URL")
    return url


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fetch(url, maximum_bytes, records, headers=None, method="GET"):
    allowed_url(url)
    if maximum_bytes < 0 or maximum_bytes > BUDGET_BYTES-sum(row.get("bytes_received",0) for row in records):
        raise ValueError("Response reservation exceeds aggregate source byte budget")
    for attempt in range(1, 3):
        record = {"url": url, "method": method, "attempt": attempt,
                  "request_headers": headers or {}, "bytes_received": 0}
        records.append(record)
        try:
            native = subprocess.run(["pwsh","-NoProfile","-NonInteractive","-File",
                str(Path(__file__).with_name("verified_http.ps1")),"-Url",url,
                "-MaximumBytes",str(maximum_bytes),"-Method",method,
                *([] if not headers or "Range" not in headers else ["-Range",headers["Range"]])],
                capture_output=True,text=True,timeout=40)
            if native.returncode != 0:
                raise OSError("Native verified HTTP helper failed: "+native.stderr[:500])
            payload=json.loads(native.stdout)
            record.update({k:v for k,v in payload.items() if k not in ("body_base64",)})
            if payload.get("error"):
                if record.get("status") is not None:
                    raise ValueError(payload["error"])
                raise OSError(payload["error"])
            data=base64.b64decode(payload.get("body_base64",""),validate=True)
            if len(data)>maximum_bytes:
                raise ValueError("Response exceeds the hard byte limit")
            record["bytes_received"]=len(data)
            record["sha256"]=sha256(data)
            record["transport"]="Windows .NET default verified TLS"
            return data,record
        except (urllib.error.URLError, OSError) as error:
            record["error"] = str(error)
            if attempt == 2: raise
        except ValueError as error:
            record["error"] = str(error)
            raise
    raise RuntimeError("Unreachable retry state")


class RemoteZip(io.RawIOBase):
    """Seekable HTTP ranges with exact response and aggregate byte checks."""
    def __init__(self, url, license_id, records, maximum_bytes=BUDGET_BYTES):
        if license_id != "CC-BY-4.0":
            raise ValueError("Archive license must be verified before reading data bytes")
        self.url, self.records, self.maximum_bytes = allowed_url(url), records, maximum_bytes
        _, head = fetch(url, 0, records, method="HEAD")
        self.length = int(head["response_headers"].get("Content-Length", "0"))
        if self.length <= 0: raise ValueError("Archive size is unavailable")
        self.position = 0
        self.downloaded_bytes = 0

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.position
    def seek(self, offset, whence=0):
        position = offset if whence == 0 else self.position + offset if whence == 1 else self.length + offset
        if not 0 <= position <= self.length: raise ValueError("Seek outside declared archive")
        self.position = position
        return position

    def read(self, size=-1):
        size = self.length - self.position if size is None or size < 0 else min(size, self.length-self.position)
        if size == 0: return b""
        if size > 8*1024*1024 or self.downloaded_bytes+size > self.maximum_bytes:
            raise ValueError("HTTP range exceeds per-request or aggregate byte budget")
        start, end = self.position, self.position+size-1
        data, record = fetch(self.url, size, self.records, headers={"Range": f"bytes={start}-{end}"})
        if record.get("status") != 206:
            raise ValueError("Archive server did not return 206")
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", record["response_headers"].get("Content-Range", ""))
        if not match or tuple(map(int,match.groups())) != (start,end,self.length) or len(data) != size:
            raise ValueError("Content-Range or actual range byte count is inconsistent")
        self.position += len(data)
        self.downloaded_bytes += len(data)
        return data


def audit(out: Path, select_member=False):
    out.mkdir(parents=True,exist_ok=True)
    records, audit_data = [], {"source_id":SOURCE_ID, "record_url":RECORD_URL,
        "doi":"10.18154/RWTH-2024-05745", "license_id":None, "status":"in_progress",
        "full_archive_downloaded":False, "archive_sha256":None}
    try:
        for filename, suffix, limit in [
            ("record.html","",2*1024*1024),
            ("rights.xml","/export/xd?ln=en",2*1024*1024),
            ("ReadMe.pdf","/files/ReadMe.pdf",1024*1024),
            ("source_reader_unexecuted.py","/files/Read_Data-Copy_file_to_folder_after_extraction.py",128*1024)]:
            data, metadata = fetch(RECORD_URL+suffix,limit,records)
            if b"/fast-challenge/" in data.lower():
                rejected="rejected_"+filename.replace(".","_")+".html"
                (out/rejected).write_bytes(data)
                audit_data["rejected_response"]={"artifact":rejected,"sha256":sha256(data),
                    "bytes":len(data),"kind":"javascript_challenge_not_source_content"}
                raise ValueError("Source returned a JavaScript challenge instead of the requested metadata")
            if filename=="ReadMe.pdf" and not data.startswith(b"%PDF-"):
                raise ValueError("ReadMe response is not a PDF")
            (out/filename).write_bytes(data)
            audit_data.setdefault("metadata_files",{})[filename]={"sha256":sha256(data),"bytes":len(data)}
        rights=(out/"rights.xml").read_text(encoding="utf-8")
        if "creativecommons.org/licenses/by/4.0" not in rights.lower() and "cc by 4.0" not in rights.lower():
            raise ValueError("CC-BY-4.0 not confirmed by institution rights export")
        audit_data["license_id"]="CC-BY-4.0"
        audit_data["license_evidence"]={"url":RECORD_URL+"/export/xd?ln=en",
            "artifact":"rights.xml","sha256":audit_data["metadata_files"]["rights.xml"]["sha256"]}
        remote=RemoteZip(ZIP_URL,"CC-BY-4.0",records)
        with zipfile.ZipFile(remote) as archive:
            infos=archive.infolist()
            listing=[{"name":i.filename,"uncompressed_bytes":i.file_size,"compressed_bytes":i.compress_size,
                      "crc32":f"{i.CRC:08x}","local_header_offset":i.header_offset,
                      "compression":i.compress_type} for i in infos]
            (out/"archive_members.json").write_text(json.dumps(listing,indent=2),encoding="utf-8")
            audit_data["archive_size_bytes"]=remote.length
            audit_data["member_count"]=len(infos)
            if select_member:
                candidates=[i for i in infos if i.filename.lower().endswith((".csv",".txt"))
                    and 10_000 <= i.file_size <= 5*1024*1024 and 0 < i.compress_size <= 5*1024*1024
                    and i.file_size/i.compress_size <= 200]
                if not candidates: raise ValueError("No bounded complete CSV/text member found")
                chosen=min(candidates,key=lambda item:item.file_size)
                parts=PurePosixPath(chosen.filename).parts
                if chosen.filename.startswith(("/", "\\")) or ".." in parts or ":" in chosen.filename:
                    raise ValueError("Unsafe archive member")
                data=archive.read(chosen)
                if len(data) != chosen.file_size:
                    raise ValueError("Selected member did not decompress to its declared length")
                filename="raw_selected_member"+Path(chosen.filename).suffix.lower()
                (out/filename).write_bytes(data)
                audit_data["selected_member"]={"archive_url":ZIP_URL,"member_name":chosen.filename,
                    "local_artifact":filename,"sha256":sha256(data),"bytes":len(data),
                    "compressed_bytes":chosen.compress_size,"crc32":f"{chosen.CRC:08x}",
                    "crc_verified":True,"local_header_offset":chosen.header_offset,
                    "complete_member":True,"license_id":"CC-BY-4.0"}
            audit_data["archive_range_bytes_received"]=remote.downloaded_bytes
        audit_data["status"]="downloaded_member_pending_field_audit" if select_member else "archive_inventory_read"
    except Exception as error:
        audit_data.update(status="blocked",error_type=type(error).__name__,reason=str(error))
    finally:
        audit_data["requests"]=records
        audit_data["all_received_bytes"]=sum(row["bytes_received"] for row in records)
        audit_data["budget_bytes"]=BUDGET_BYTES
        (out/"download_audit.json").write_text(json.dumps(audit_data,indent=2),encoding="utf-8")
    return audit_data


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--select-small-member",action="store_true")
    args=parser.parse_args()
    result=audit(args.out,args.select_small_member)
    print(json.dumps({k:v for k,v in result.items() if k!="requests"},indent=2))
    return 2 if result["status"]=="blocked" else 0


if __name__ == "__main__": raise SystemExit(main())
