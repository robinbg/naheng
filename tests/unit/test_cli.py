from naheng.cli import main
def test_unknown_scenario_is_not_success(tmp_path):
    assert main(["demo","--scenario","does-not-exist","--out",str(tmp_path)])!=0
def test_incomplete_release_is_blocked(tmp_path):
    assert main(["verify","--profile","release","--out",str(tmp_path/"audit.json")])!=0
