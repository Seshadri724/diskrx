"""Integration tests using Click's CliRunner."""
from click.testing import CliRunner
from dxcli.cli import cli

runner = CliRunner()

def test_status_runs():
    result = runner.invoke(cli, ['status'])
    assert result.exit_code == 0
    assert "Disk Status" in result.output

def test_diagnose_runs():
    result = runner.invoke(cli, ['diagnose', '.'])
    assert result.exit_code == 0
    assert "Disk Diagnosis" in result.output or "TOP CONSUMERS" in result.output

def test_default_runs_diagnose():
    """Running 'dxcli' with no subcommand should default to diagnose."""
    result = runner.invoke(cli, [])
    assert result.exit_code == 0
    assert "Disk Diagnosis" in result.output or "TOP CONSUMERS" in result.output

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
