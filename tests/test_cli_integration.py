"""Integration tests using Click's CliRunner."""
import json
import pytest


from click.testing import CliRunner

from dxcli.cli import cli

runner = CliRunner()


@pytest.fixture(autouse=True)
def mock_collectors(mocker):
    import os
    import pytest
    from dxcli.store.models import DirNode, UnrotatedLog, StaleFile
    
    def mock_dir_scan(self, path, *args, **kwargs):
        return [
            DirNode(path=os.path.abspath(os.path.join(path, "logs")), size_bytes=500000, file_count=5),
            DirNode(path=os.path.abspath(os.path.join(path, "stale")), size_bytes=100000, file_count=2),
        ]
        
    def mock_log_scan(self, paths, *args, **kwargs):
        res = []
        for p in paths:
            res.append(UnrotatedLog(path=os.path.abspath(os.path.join(p, "logs", "app.log")), size_bytes=400000, last_modified_timestamp=1234567, has_logrotate_config=False))
        return res
        
    def mock_stale_scan(self, paths, *args, **kwargs):
        res = []
        for p in paths:
            res.append(StaleFile(path=os.path.abspath(os.path.join(p, "stale", "old.tmp")), size_bytes=100000, last_accessed_timestamp=1234567, days_stale=40.0))
        return res

    def mock_get_active_writers(self, path, interval=None):
        return [
            {"pid": 9999, "name": "test_writer", "throughput_bps": 1000.0, "files": [os.path.abspath(os.path.join(path, "test.log"))]}
        ]
        
    def mock_get_application_accounting(self, path):
        return [
            {"name": "test_app", "total_bytes": 500000, "pids": [9999]}
        ]
        
    def mock_find_culprits(self, path, write_only=True):
        from dxcli.collectors.process_mapper import ProcessRef
        return [
            ProcessRef(pid=9999, name="test_writer", cmdline=[], mode="write", files=[os.path.abspath(os.path.join(path, "test.log"))])
        ]

    mocker.patch('dxcli.collectors.dir_tree.DirectoryTreeCollector.scan', mock_dir_scan)
    mocker.patch('dxcli.collectors.log_finder.LogFinderCollector.scan', mock_log_scan)
    mocker.patch('dxcli.collectors.stale_files.StaleFileCollector.scan', mock_stale_scan)
    mocker.patch('dxcli.collectors.process_mapper.ProcessMapper.get_active_writers', mock_get_active_writers)
    mocker.patch('dxcli.collectors.process_mapper.ProcessMapper.get_application_accounting', mock_get_application_accounting)
    mocker.patch('dxcli.collectors.process_mapper.ProcessMapper.find_culprits', mock_find_culprits)



def test_status_runs():
    result = runner.invoke(cli, ['status'])
    assert result.exit_code == 0
    assert "Disk Status" in result.output

def test_diagnose_runs():
    result = runner.invoke(cli, ['diagnose', '.'])
    assert result.exit_code == 0
    assert "Primary Culprit" in result.output or "DISK INTELLIGENCE REPORT" in result.output

def test_diagnose_json():
    result = runner.invoke(cli, ['diagnose', '.', '--json'])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "path" in data
    assert "top_dirs" in data
    assert "trends" in data

def test_default_runs_diagnose():
    """Running 'dxcli' with no subcommand should default to diagnose."""
    result = runner.invoke(cli, [])
    assert result.exit_code == 0
    assert "Primary Culprit" in result.output or "DISK INTELLIGENCE REPORT" in result.output

def test_predict_runs():
    result = runner.invoke(cli, ['predict', '.'])
    assert result.exit_code == 0
    # Should either show forecast or mapping error
    assert "FORECAST" in result.output or "partition" in result.output

def test_help():
    result = runner.invoke(cli, ['--help'])
    assert result.exit_code == 0
    assert "dxcli" in result.output
    assert "diagnose" in result.output
    assert "predict" in result.output
    assert "watch" in result.output
    assert "serve" in result.output
    assert "dash" in result.output


def test_diagnose_invalid_target_exits_with_validation_code():
    result = runner.invoke(cli, ["diagnose", ".", "--target", "missing-target"])
    assert result.exit_code == 2
    assert "not found in config" in result.output


def test_fleet_without_hosts_exits_with_validation_code():
    result = runner.invoke(cli, ["fleet"])
    assert result.exit_code == 2
    assert "Usage: dxcli fleet" in result.output


def test_diagnose_tempdir_non_empty(tmp_path):
    d = tmp_path / "subdir"
    d.mkdir()
    f = d / "test.log"
    f.write_text("hello world " * 100)
    
    result = runner.invoke(cli, ["diagnose", str(tmp_path)])
    assert result.exit_code == 0
    assert len(result.output) > 0


def test_diagnose_json_contents(tmp_path):
    result = runner.invoke(cli, ["diagnose", "--json", str(tmp_path)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "top_dirs" in data
    assert "prediction" in data
    assert "anomalies" in data


def test_heal_dry_run_no_removal(tmp_path):
    target = tmp_path / "stale.file"
    target.write_text("stale data")
    import os
    import time
    stale_ts = time.time() - (40 * 86400)
    os.utime(target, (stale_ts, stale_ts))
    
    result = runner.invoke(cli, ["heal", str(tmp_path), "--dry-run", "-y"])
    assert result.exit_code == 0
    assert "DRY RUN SIMULATION" in result.output
    assert target.exists()


def test_undo_empty_stack():
    from dxcli.runtime import ExitCode
    result = runner.invoke(cli, ["undo"])
    assert result.exit_code == int(ExitCode.RUNTIME_ERROR)


def test_predict_nonexistent():
    from dxcli.runtime import ExitCode
    # Windows absolute invalid path Z:\nonexistent
    result = runner.invoke(cli, ["predict", "Z:\\nonexistent"])
    assert result.exit_code == int(ExitCode.VALIDATION_ERROR)


def test_serve_bind_0_0_0_0_no_token():
    from dxcli.runtime import ExitCode
    result = runner.invoke(cli, ["serve", "--bind", "0.0.0.0"])
    assert result.exit_code == int(ExitCode.UNSAFE_OPERATION)
    assert "refused without --auth-token" in result.output


def test_diagnose_classify_runs(tmp_path):
    """BUG-1 regression: diagnose --classify must not crash."""
    result = runner.invoke(cli, ["diagnose", "--classify", str(tmp_path)])
    assert result.exit_code == 0
    assert "Semantic Usage" in result.output or "Category" in result.output


def test_explain_runs(tmp_path):
    result = runner.invoke(cli, ["explain", str(tmp_path)])
    assert result.exit_code == 0
    assert "is growing" in result.output or "is stable" in result.output
    assert "Fix: " in result.output
    assert "Root cause: " in result.output


def test_predict_ranges_and_variance(tmp_path, mocker):
    from dxcli.store.models import PredictionResult
    import time

    mocker.patch(
        "dxcli.analyzers.DiskPredictor.predict_full_date",
        return_value=PredictionResult(
            path=str(tmp_path),
            date_full_timestamp=None,
            days_until_full=None,
            current_capacity_bytes=1000000,
            current_usage_bytes=500000,
            daily_growth_bytes=200000,
            is_accelerating=False,
            days_until_full_low=None,
            days_until_full_high=None,
            hint="high variance"
        )
    )
    result = runner.invoke(cli, ["predict", str(tmp_path)])
    assert result.exit_code == 0
    assert "Unpredictable (high variance)" in result.output

    mocker.patch(
        "dxcli.analyzers.DiskPredictor.predict_full_date",
        return_value=PredictionResult(
            path=str(tmp_path),
            date_full_timestamp=time.time() + (6.0 * 86400),
            days_until_full=6.0,
            current_capacity_bytes=1000000,
            current_usage_bytes=500000,
            daily_growth_bytes=200000,
            is_accelerating=True,
            days_until_full_low=5.0,
            days_until_full_high=7.0,
            hint=None
        )
    )
    result = runner.invoke(cli, ["predict", str(tmp_path)])
    assert result.exit_code == 0
    assert "5–7 days" in result.output or "5-7 days" in result.output

    mocker.patch(
        "dxcli.analyzers.DiskPredictor.predict_full_date",
        return_value=PredictionResult(
            path=str(tmp_path),
            date_full_timestamp=time.time() + (400.0 * 86400),
            days_until_full=400.0,
            current_capacity_bytes=1000000,
            current_usage_bytes=500000,
            daily_growth_bytes=100,
            is_accelerating=False,
            days_until_full_low=390.0,
            days_until_full_high=410.0,
            hint=None
        )
    )
    result = runner.invoke(cli, ["predict", str(tmp_path)])
    assert result.exit_code == 0
    assert "Stable (fills in >1 year)" in result.output


def test_tui_app_instantiation():
    from dxcli.outputs.tui import DxApp
    app = DxApp(watch_mode=True, path=".", interval=5.0)
    assert app.watch_mode is True
    assert app.watch_interval == 5.0


