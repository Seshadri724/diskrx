import os
import pytest
from click.testing import CliRunner
from dxcli.cli import cli, serve
from dxcli.heal_engine import HealEngine
from dxcli.outputs.notifier import send_webhook
from dxcli.store.models import Prescription

def test_webhook_url_validation():
    """Test that webhooks validate URL schemes and reject invalid ones."""
    success, msg = send_webhook("not-a-url", {"text": "hello"})
    assert not success
    assert "Invalid webhook scheme" in msg
    
    success, msg = send_webhook("ftp://example.com/hook", {"text": "hello"})
    assert not success
    assert "Invalid webhook scheme" in msg

def test_heal_path_scope_validation(tmp_path):
    """Test that HealEngine rejects actions outside its allowed scope."""
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    
    engine = HealEngine(allowed_scope=str(allowed_dir))
    
    # Valid scope
    valid_p = Prescription(
        id="1", name="Valid", action_type="delete", 
        target_path=str(allowed_dir / "target.log"),
        description="", category="", severity="high", size_savings_bytes=0, is_safe=True
    )
    # Should fail due to file not existing, but not rejected for scope
    assert not engine.execute(valid_p)
    assert any("delete_fail" in action["action"] for action in engine.session_actions)

    # Invalid scope
    invalid_p = Prescription(
        id="2", name="Invalid", action_type="delete", 
        target_path=str(outside_dir / "target.log"),
        description="", category="", severity="high", size_savings_bytes=0, is_safe=True
    )
    assert not engine.execute(invalid_p)
    assert any("reject" in action["action"] for action in engine.session_actions)

def test_daemon_safe_args():
    """Test that daemon only accepts predefined commands."""
    runner = CliRunner()
    result = runner.invoke(cli, ['daemon', 'start', '--command', 'invalid_cmd'])
    assert result.exit_code != 0
    assert "Invalid value for '--command'" in result.output

def test_diagnose_plugins_disabled_by_default(mocker):
    """Test that plugins are not loaded unless explicitly enabled."""
    runner = CliRunner()
    mock_plugin_loader = mocker.patch('dxcli.analyzers.plugin_loader.PluginLoader.load_plugins')
    
    with runner.isolated_filesystem():
        # Without flag
        result = runner.invoke(cli, ['diagnose', '.', '--json'])
        assert result.exit_code == 0
        mock_plugin_loader.assert_not_called()
        
        # With flag
        result = runner.invoke(cli, ['diagnose', '.', '--json', '--enable-plugins'])
        assert result.exit_code == 0
        mock_plugin_loader.assert_called_once()
