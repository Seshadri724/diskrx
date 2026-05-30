import json

from click.testing import CliRunner

from dxcli.cli import cli
from dxcli.enterprise import AgentSnapshotCollector, build_risk_signals, risk_level
from dxcli.store.models import DirNode, Partition, PolicyViolation


class FakeProvider:
    def get_partitions(self):
        return [
            Partition(
                device="disk0",
                mountpoint="/",
                fstype="ext4",
                total_bytes=100,
                used_bytes=92,
                free_bytes=8,
            )
        ]


class FakePolicyEngine:
    def evaluate(self, top_dirs, logs, stales):
        return [
            PolicyViolation(
                rule_name="Owner Required",
                path=top_dirs[0].path if top_dirs else "/unknown",
                message="Storage owner is missing",
                severity="warning",
                suggested_action="Assign owner metadata",
            )
        ]


def test_risk_level_thresholds():
    assert risk_level(0) == "healthy"
    assert risk_level(35) == "warning"
    assert risk_level(65) == "high"
    assert risk_level(90) == "critical"


def test_build_risk_signals_orders_highest_score_first():
    partition = Partition(
        device="disk0",
        mountpoint="/",
        fstype="ext4",
        total_bytes=100,
        used_bytes=96,
        free_bytes=4,
    )
    directory = DirNode(path="/var/log", size_bytes=30 * 1024**3, file_count=10)
    violation = PolicyViolation(
        rule_name="Limit",
        path="/var/log",
        message="Directory exceeds limit",
        severity="warning",
        suggested_action="Archive",
    )

    signals = build_risk_signals([partition], [directory], [violation], "/")

    assert signals[0].severity == "critical"
    assert signals[0].score == 100
    assert {signal.category for signal in signals} == {"capacity", "growth-source", "policy"}


def test_agent_snapshot_collector_builds_fleet_ready_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr("dxcli.state.get_state_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        "dxcli.collectors.dir_tree.DirectoryTreeCollector.scan",
        lambda self, path: [DirNode(path=str(tmp_path / "logs"), size_bytes=30 * 1024**3, file_count=12)],
    )
    monkeypatch.setattr("dxcli.collectors.log_finder.LogFinderCollector.scan", lambda self, paths: [])
    monkeypatch.setattr("dxcli.collectors.stale_files.StaleFileCollector.scan", lambda self, paths: [])

    snapshot = AgentSnapshotCollector(provider=FakeProvider(), policy_engine=FakePolicyEngine()).collect(str(tmp_path))

    assert snapshot.schema_version == "dxcli.host_snapshot.v1"
    assert snapshot.risk_level == "critical"
    assert snapshot.risk_score == 90
    assert snapshot.policy_violations[0].rule_name == "Owner Required"
    assert snapshot.host_id
    assert (tmp_path / "agent_id").exists()


def test_agent_snapshot_collector_records_partial_failures(monkeypatch, tmp_path):
    monkeypatch.setattr("dxcli.state.get_state_dir", lambda: str(tmp_path))

    def fail_scan(self, path):
        raise OSError("scan failed")

    monkeypatch.setattr("dxcli.collectors.dir_tree.DirectoryTreeCollector.scan", fail_scan)
    monkeypatch.setattr("dxcli.collectors.log_finder.LogFinderCollector.scan", lambda self, paths: [])
    monkeypatch.setattr("dxcli.collectors.stale_files.StaleFileCollector.scan", lambda self, paths: [])

    snapshot = AgentSnapshotCollector(provider=FakeProvider(), policy_engine=FakePolicyEngine()).collect(str(tmp_path))

    assert snapshot.top_dirs == []
    assert snapshot.collector_errors[0].collector == "directory_tree"


def test_snapshot_command_outputs_json(monkeypatch, tmp_path):
    monkeypatch.setattr("dxcli.state.get_state_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        "dxcli.collectors.dir_tree.DirectoryTreeCollector.scan",
        lambda self, path: [DirNode(path=str(tmp_path / "logs"), size_bytes=30 * 1024**3, file_count=12)],
    )
    monkeypatch.setattr("dxcli.collectors.log_finder.LogFinderCollector.scan", lambda self, paths: [])
    monkeypatch.setattr("dxcli.collectors.stale_files.StaleFileCollector.scan", lambda self, paths: [])
    monkeypatch.setattr("dxcli.enterprise.AgentSnapshotCollector.__init__", lambda self: None)
    monkeypatch.setattr("dxcli.enterprise.AgentSnapshotCollector.provider", FakeProvider(), raising=False)
    monkeypatch.setattr("dxcli.enterprise.AgentSnapshotCollector.policy_engine", FakePolicyEngine(), raising=False)

    result = CliRunner().invoke(cli, ["snapshot", str(tmp_path), "--json", "--max-items", "1"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "dxcli.host_snapshot.v1"
    assert payload["risk_level"] == "critical"
    assert payload["risk_signals"]
    assert "collector_errors" in payload
