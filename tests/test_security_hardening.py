import pytest
from click.testing import CliRunner

from dxcli.analyzers.plugin_loader import PluginLoader
from dxcli.cli import cli
from dxcli.heal_engine import HealEngine
from dxcli.outputs.html_report import generate_html_report
from dxcli.outputs.metrics import create_metrics_server
from dxcli.outputs.notifier import send_webhook
from dxcli.runtime import ExitCode
from dxcli.store.models import DirNode, Partition, Prescription

runner = CliRunner()


def test_plugin_loader_skips_symlink(monkeypatch, tmp_path):
    state_dir = tmp_path / ".dx"
    state_dir.mkdir()
    monkeypatch.setattr("dxcli.state.get_state_dir", lambda: str(state_dir))

    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    target = plugin_dir / "real_plugin.py"
    target.write_text(
        """
from dxcli.analyzers.base import AnalyzerPlugin
class RealPlugin(AnalyzerPlugin):
    @property
    def name(self): return "RealPlugin"
    def analyze(self, top_dirs, logs, stales): return []
""",
        encoding="utf-8",
    )

    from dxcli.analyzers.plugin_loader import compute_sha256

    target_sha = compute_sha256(str(target))

    allowlist_file = state_dir / "plugins.allowlist"
    allowlist_file.write_text(
        f"{target_sha}  real_plugin.py\n{target_sha}  linked_plugin.py\n",
        encoding="utf-8",
    )

    link = plugin_dir / "linked_plugin.py"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks not supported in this environment")

    plugins = PluginLoader(str(plugin_dir)).load_plugins()
    assert len(plugins) == 1
    assert plugins[0].__class__.__name__ == "RealPlugin"


def test_plugin_loader_allowlist(monkeypatch, tmp_path):
    state_dir = tmp_path / ".dx"
    state_dir.mkdir()
    monkeypatch.setattr("dxcli.state.get_state_dir", lambda: str(state_dir))

    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()

    plugin_file = plugin_dir / "my_plugin.py"
    plugin_file.write_text(
        """
from dxcli.analyzers.base import AnalyzerPlugin
class MyPlugin(AnalyzerPlugin):
    @property
    def name(self): return "MyPlugin"
    def analyze(self, top_dirs, logs, stales): return []
""",
        encoding="utf-8",
    )

    from dxcli.analyzers.plugin_loader import compute_sha256, PluginLoader

    file_sha = compute_sha256(str(plugin_file))

    loader = PluginLoader(str(plugin_dir))
    plugins = loader.load_plugins()
    assert plugins == []

    allowlist_file = state_dir / "plugins.allowlist"
    allowlist_file.write_text(f"{file_sha}  my_plugin.py\n", encoding="utf-8")

    plugins = loader.load_plugins()
    assert len(plugins) == 1
    assert plugins[0].__class__.__name__ == "MyPlugin"


def test_heal_engine_rejects_path_outside_scope(tmp_path):
    scope = tmp_path / "scope"
    scope.mkdir()
    outside = tmp_path / "outside.log"
    outside.write_text("data", encoding="utf-8")

    engine = HealEngine(allowed_scope=str(scope))
    prescription = Prescription(
        id="danger",
        name="delete outside",
        description="attempt to delete outside scope",
        category="test",
        severity="high",
        size_savings_bytes=4,
        action_type="delete",
        target_path=str(outside),
        template="manual",
        risk="high",
        is_safe=False,
    )

    assert engine.execute(prescription) is False
    assert outside.exists()


def test_send_webhook_rejects_invalid_scheme():
    success, error = send_webhook("file:///tmp/out", {"text": "hello"})
    assert success is False
    assert "Invalid webhook scheme" in error


def test_send_webhook_rejects_private_destinations():
    success, error = send_webhook("http://127.0.0.1/hook", {"text": "hello"})
    assert success is False
    assert "private" in error or "loopback" in error


def test_html_report_escapes_dynamic_values(tmp_path):
    out_path = tmp_path / "report.html"
    generate_html_report(
        str(out_path),
        "<script>alert(1)</script>",
        Partition("dev", 'C:"<bad>', "ntfs", 100, 50, 50),
        [DirNode("<img src=x onerror=alert(1)>", 10, 1)],
        [],
        [],
        prescriptions=[
            Prescription(
                id="p",
                name="<script>alert(2)</script>",
                description="x",
                category="x",
                severity="low",
                size_savings_bytes=1,
            )
        ],
    )

    html = out_path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "<script>alert(2)</script>" not in html
    assert "&lt;script&gt;alert" in html


def test_heal_backup_id_is_sanitized(monkeypatch, tmp_path):
    state_dir = tmp_path / ".dx"
    monkeypatch.setattr("dxcli.state.get_state_dir", lambda: str(state_dir))
    scope = tmp_path / "scope"
    scope.mkdir()
    target = scope / "old.log"
    target.write_text("data", encoding="utf-8")
    engine = HealEngine(allowed_scope=str(scope))
    prescription = Prescription(
        id="../escape",
        name="delete",
        description="delete",
        category="test",
        severity="high",
        size_savings_bytes=4,
        action_type="delete",
        target_path=str(target),
        is_safe=False,
    )

    assert engine.execute(prescription) is True
    backups = list((state_dir / "backups").glob("*"))
    backup_names = [path.name for path in backups]
    assert all(
        ".." not in name and "/" not in name and "\\" not in name
        for name in backup_names
    )


def test_serve_bind_conflict_returns_runtime_error(monkeypatch):
    def fake_create_metrics_server(*args, **kwargs):
        raise OSError("address already in use")

    monkeypatch.setattr(
        "dxcli.outputs.metrics.create_metrics_server", fake_create_metrics_server
    )
    result = runner.invoke(cli, ["serve", "--port", "9100", "."])
    assert result.exit_code == ExitCode.RUNTIME_ERROR
    assert "Could not start metrics server" in result.output


def test_watch_invalid_webhook_returns_validation_error():
    result = runner.invoke(
        cli, ["watch", "--interval", "1", "--webhook", "ftp://bad", "."]
    )
    assert result.exit_code == ExitCode.VALIDATION_ERROR
    assert "Invalid webhook URL" in result.output


def test_create_metrics_server_binds_and_closes():
    server = create_metrics_server(0, "127.0.0.1")
    try:
        assert server.server_address[1] > 0
    finally:
        server.server_close()


def test_policy_scope_does_not_match_prefix_siblings():
    from dxcli.policy_engine import PolicyEngine
    from dxcli.store.models import DirNode

    engine = PolicyEngine()
    engine.rules = [
        {
            "name": "Var Log Limit",
            "type": "limit",
            "path": "/var/log",
            "max_size_gb": 1,
            "action": "cleanup",
        }
    ]

    dirs = [
        DirNode(path="/var/logbomb", size_bytes=2 * (1024**3), file_count=1),
        DirNode(path="/var/log/nginx", size_bytes=2 * (1024**3), file_count=1),
        DirNode(path="/var/log", size_bytes=2 * (1024**3), file_count=1),
    ]

    violations = engine.evaluate(dirs, [], [])
    violated_paths = {v.path for v in violations}

    assert "/var/logbomb" not in violated_paths
    assert "/var/log/nginx" in violated_paths
    assert "/var/log" in violated_paths


def test_process_mapper_does_not_match_prefix_siblings():
    """Ensure /var/log doesn't match /var/logbomb in process mapper."""
    from dxcli.collectors.process_mapper import ProcessMapper
    import os

    mapper = ProcessMapper()

    # Use absolute paths that work cross-platform
    base = os.path.abspath(os.sep + "var")
    log_dir = os.path.join(base, "log")
    logbomb_dir = os.path.join(base, "logbomb")
    logbomb_file = os.path.join(logbomb_dir, "data.txt")

    # Simulate a cache with a process that has files in /var/logbomb
    mapper._process_cache = {
        1234: {
            "name": "test_proc",
            "cmdline": ["test"],
            "paths": [logbomb_file],
            "modes": ["w"],
        }
    }

    # Searching /var/log should NOT find the process with files in /var/logbomb
    culprits = mapper.find_culprits(log_dir, write_only=False)
    assert len(culprits) == 0

    # But searching /var/logbomb should find it
    culprits = mapper.find_culprits(logbomb_dir, write_only=False)
    assert len(culprits) == 1
    assert culprits[0].pid == 1234
