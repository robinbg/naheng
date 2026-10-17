"""Explicit container-internal entry; host exposure is controlled by compose."""
from pathlib import Path


def main():
    import uvicorn
    from naheng.api.app import create_app
    from naheng.runtime.execution_environment import capture_environment
    from start_local import verify_delivery
    root=Path(__file__).resolve().parents[1]
    verify_delivery(root);capture_environment(root)
    # Ordinary naheng CLI loopback checks remain unchanged.
    uvicorn.run(create_app(root),host='0.0.0.0',port=8000)


if __name__=='__main__':main()
