import sys
from pathlib import Path
from .jobs import JobStore
from .runner import execute
if __name__ == "__main__":
    root=Path(sys.argv[1]); store=JobStore(root/"artifacts/runs")
    execute(root,store,sys.argv[2])
