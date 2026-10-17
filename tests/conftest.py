from pathlib import Path
def pytest_configure(config):
    root=Path(__file__).resolve().parents[1]
    if config.option.basetemp is None:
        config.option.basetemp=str(root/"artifacts/test-temp/default")
    Path(config.option.basetemp).parent.mkdir(parents=True,exist_ok=True)
