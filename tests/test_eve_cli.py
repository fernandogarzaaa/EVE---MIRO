"""EVE CLI argv: .js entries must be launched with node (Windows cannot exec them)."""

from pathlib import Path

from eve_miro.core.experience.eve_cli import eve_trajectory_command


def test_explicit_js_bin_is_prefixed_with_node(tmp_path):
    js = tmp_path / "eve.js"
    js.write_text("console.log('ok');\n", encoding="utf-8")
    cmd = eve_trajectory_command(bin_path=str(js))
    assert cmd[0] == "node"
    assert cmd[1] == str(js)
    assert cmd[2:] == ["trajectory", "--stdin"]
