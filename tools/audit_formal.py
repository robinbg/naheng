"""Standalone formal checker; final exit codes are 0 checked, 1 failed, 2 blocked."""

from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from naheng.formal.checker import check

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="foundation")
    parser.add_argument("--out", type=Path, default=Path("artifacts/formal/foundation"))
    args = parser.parse_args()
    result = check(args.suite, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(result["exit_code"])
