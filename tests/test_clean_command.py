import json
import os
from click.testing import CliRunner
from dxcli.clean_engine import CleanEngine, is_path_protected
from dxcli.cli import cli


def test_is_path_protected():
    assert is_path_protected("/") is True
    assert is_path_protected("/usr") is True
    assert is_path_protected("C:\\Windows") is True
    assert is_path_protected(os.path.expanduser("~")) is True


def test_clean_engine_discovers_and_purges_disposable(tmp_path):
    # Setup dummy project artifacts
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / "package.json").write_text("{}")

    pytest_cache = tmp_path / ".pytest_cache"
    pytest_cache.mkdir()
    (pytest_cache / "v").write_text("cache")

    engine = CleanEngine(state_dir=str(tmp_path / ".dx"))
    plan = engine.create_plan(str(tmp_path), include_docker=False)

    assert len(plan.targets) >= 2
    assert plan.dry_run is True

    # Execute plan
    result = engine.execute_plan(plan)

    assert result.freed_bytes > 0
    assert not node_modules.exists()
    assert not pytest_cache.exists()

    # Check audit log
    audit_file = tmp_path / ".dx" / "audit.log"
    assert audit_file.exists()
    audit_lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(audit_lines) == 1
    log_entry = json.loads(audit_lines[0])
    assert log_entry["freed_bytes"] == result.freed_bytes


def test_cli_clean_dry_run_does_not_delete(tmp_path):
    target_dir = tmp_path / "dist"
    target_dir.mkdir()
    (target_dir / "app.js").write_text("console.log(1)")

    runner = CliRunner()
    res = runner.invoke(cli, ["clean", str(tmp_path), "--no-docker"])

    assert res.exit_code == 0
    assert "DRY-RUN" in res.output
    assert target_dir.exists()


def test_cli_clean_yes_executes_cleanup(tmp_path):
    target_dir = tmp_path / "dist"
    target_dir.mkdir()
    (target_dir / "app.js").write_text("console.log(1)")

    runner = CliRunner()
    res = runner.invoke(cli, ["clean", str(tmp_path), "--no-docker", "--yes"])

    assert res.exit_code == 0
    assert "Cleanup complete" in res.output
    assert not target_dir.exists()
