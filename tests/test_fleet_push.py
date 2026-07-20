import json
import os
import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from fastapi.testclient import TestClient

from dxcli.cli import cli
from dxcli.server.main import app, init_db
from dxcli.runtime import ExitCode


# 1. FastAPI Server Integration Tests
def test_fastapi_endpoints(tmp_path):
    temp_db = tmp_path / "test_fleet.db"
    with patch.dict(os.environ, {"DX_FLEET_DB": str(temp_db), "DX_API_TOKEN": "my-secret-token"}):
        init_db()
        client = TestClient(app)

        # Test auth rejection (HTTPBearer returns 401 or 403 on missing auth header)
        resp = client.post("/v1/snapshots", json={})
        assert resp.status_code in (401, 403)

        # Test auth success and invalid snapshot
        headers = {"Authorization": "Bearer my-secret-token"}
        resp = client.post("/v1/snapshots", json={}, headers=headers)
        assert resp.status_code == 400
        assert "Missing host_id" in resp.json()["detail"]

        # Valid snapshot
        valid_snapshot = {
            "schema_version": "dxcli.host_snapshot.v1",
            "host_id": "test-host-uuid",
            "hostname": "test-host",
            "platform": "Linux",
            "timestamp": 1234567.89,
            "scan_path": "/var/log",
            "partitions": [
                {
                    "device": "disk0",
                    "mountpoint": "/",
                    "fstype": "ext4",
                    "total_bytes": 1000,
                    "used_bytes": 800,
                    "free_bytes": 200,
                    "usage_percent": 80.0
                }
            ],
            "risk_score": 40,
            "risk_level": "warning"
        }
        resp = client.post("/v1/snapshots", json=valid_snapshot, headers=headers)
        assert resp.status_code == 202
        assert resp.json() == {"status": "accepted"}

        # Query fleet status
        resp = client.get("/v1/fleet/status", headers=headers)
        assert resp.status_code == 200
        hosts = resp.json()["hosts"]
        assert len(hosts) == 1
        assert hosts[0]["hostname"] == "test-host"
        assert hosts[0]["risk_level"] == "warning"
        assert hosts[0]["partitions"][0]["usage_percent"] == 80.0


# 2. CLI Push Integration Tests
def test_cli_snapshot_push_requires_token(tmp_path):
    runner = CliRunner()
    with patch.dict(os.environ, {"DX_API_TOKEN": ""}):
        result = runner.invoke(cli, ["snapshot", "--push", "http://localhost:8080/v1/snapshots"])
        assert result.exit_code == ExitCode.VALIDATION_ERROR
        assert "requires --token or env DX_API_TOKEN" in result.output


def test_cli_snapshot_push_invalid_url():
    runner = CliRunner()
    result = runner.invoke(cli, ["snapshot", "--push", "http://127.0.0.1/v1/snapshots", "--token", "foo"])
    assert result.exit_code == ExitCode.VALIDATION_ERROR
    assert "Invalid push destination URL" in result.output


def test_cli_snapshot_push_success(tmp_path, monkeypatch):
    runner = CliRunner()

    # Mock snapshot collection
    from dxcli.store.models import HostSnapshot
    mock_snapshot = HostSnapshot(
        schema_version="dxcli.host_snapshot.v1",
        host_id="uuid",
        hostname="test-host",
        platform="Linux",
        timestamp=100.0,
        scan_path="/var/log",
        partitions=[],
        top_dirs=[],
        logs=[],
        stales=[],
        policy_violations=[],
        risk_signals=[],
        risk_score=0,
        risk_level="healthy",
        collector_errors=[]
    )
    monkeypatch.setattr("dxcli.enterprise.AgentSnapshotCollector.collect", lambda self, path, *args, **kwargs: mock_snapshot)

    # Mock URL Validation to pass for localhost under test
    monkeypatch.setattr("dxcli.outputs.notifier.validate_webhook_destination", lambda url, **kwargs: (True, "", "93.184.216.34"))

    # Mock HTTP response
    mock_response = MagicMock()
    mock_response.status = 202
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.OpenerDirector.open", return_value=mock_response) as mock_open:
        result = runner.invoke(cli, ["snapshot", "--push", "http://localhost:8080/v1/snapshots", "--token", "secret"])
        assert result.exit_code == 0
        assert "successfully pushed" in result.output
        mock_open.assert_called_once()


# 3. CLI Fleet Query Integration Tests
def test_cli_fleet_server_query_success(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr("dxcli.outputs.notifier.validate_webhook_destination", lambda url, **kwargs: (True, "", "93.184.216.34"))

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({
        "hosts": [
            {
                "hostname": "remote-host",
                "risk_level": "critical",
                "partitions": [
                    {"mountpoint": "/", "usage_percent": 95.5}
                ]
            }
        ]
    }).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.OpenerDirector.open", return_value=mock_response):
        result = runner.invoke(cli, ["fleet", "--server", "http://localhost:8080", "--token", "secret"])
        assert result.exit_code == 0
        assert "remote-host" in result.output
        assert "95.5%" in result.output
        assert "CRITICAL" in result.output


def test_fastapi_endpoints_missing_server_token(tmp_path):
    temp_db = tmp_path / "test_fleet_missing.db"
    with patch.dict(os.environ, {"DX_FLEET_DB": str(temp_db), "DX_API_TOKEN": ""}):
        init_db()
        client = TestClient(app)
        headers = {"Authorization": "Bearer some-token"}
        resp = client.post("/v1/snapshots", json={}, headers=headers)
        assert resp.status_code == 500
        assert "Server security configuration error" in resp.json()["detail"]


def test_fleet_concurrency_load(tmp_path):
    import threading
    temp_db = tmp_path / "test_concurrency.db"
    with patch.dict(os.environ, {"DX_FLEET_DB": str(temp_db), "DX_API_TOKEN": "my-secret-token"}):
        init_db()
        client = TestClient(app)
        headers = {"Authorization": "Bearer my-secret-token"}

        errors = []

        def push_worker(thread_id):
            for i in range(10):
                snapshot = {
                    "schema_version": "dxcli.host_snapshot.v1",
                    "host_id": f"host-{thread_id}-{i}",
                    "hostname": f"host-{thread_id}",
                    "platform": "Linux",
                    "timestamp": 100.0 + i,
                    "partitions": [
                        {"device": "disk0", "mountpoint": "/", "fstype": "ext4", "total_bytes": 100, "used_bytes": 50, "free_bytes": 50, "usage_percent": 50.0}
                    ]
                }
                try:
                    resp = client.post("/v1/snapshots", json=snapshot, headers=headers)
                    if resp.status_code != 202:
                        errors.append(f"Thread {thread_id} failed on index {i}: {resp.status_code}")
                except Exception as e:
                    errors.append(f"Thread {thread_id} error: {e}")

        threads = [threading.Thread(target=push_worker, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrency issues encountered: {errors}"


def test_fastapi_rejects_invalid_host_id_format(tmp_path):
    temp_db = tmp_path / "test_hostid.db"
    with patch.dict(os.environ, {"DX_FLEET_DB": str(temp_db), "DX_API_TOKEN": "my-secret-token"}):
        init_db()
        client = TestClient(app)
        headers = {"Authorization": "Bearer my-secret-token"}

        # host_id with newlines (log injection attempt)
        resp = client.post("/v1/snapshots", json={"host_id": "evil\nINFO Fake log entry"}, headers=headers)
        assert resp.status_code == 400
        assert "Invalid host_id format" in resp.json()["detail"]

        # host_id with path traversal characters
        resp = client.post("/v1/snapshots", json={"host_id": "../../../etc/passwd"}, headers=headers)
        assert resp.status_code == 400
        assert "Invalid host_id format" in resp.json()["detail"]

        # Valid host_id passes
        valid = {"host_id": "prod-api-01", "hostname": "h", "partitions": []}
        resp = client.post("/v1/snapshots", json=valid, headers=headers)
        assert resp.status_code == 202


def test_fastapi_rejects_malformed_json(tmp_path):
    temp_db = tmp_path / "test_malformed.db"
    with patch.dict(os.environ, {"DX_FLEET_DB": str(temp_db), "DX_API_TOKEN": "my-secret-token"}):
        init_db()
        client = TestClient(app)
        headers = {"Authorization": "Bearer my-secret-token", "Content-Type": "application/json"}

        resp = client.post("/v1/snapshots", content=b"this is not json", headers=headers)
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["detail"]


def test_telemetry_anonymization(tmp_path):
    user_home = tmp_path / "home" / "john_doe"
    user_home.mkdir(parents=True)
    
    from dxcli.enterprise import AgentSnapshotCollector
    import socket
    
    collector = AgentSnapshotCollector()
    snapshot = collector.collect(str(user_home), anonymize=True)
    
    # Hostname is hashed and does not contain the original system hostname
    assert snapshot.hostname != socket.gethostname()
    assert snapshot.hostname.startswith("host-")
    
    # Home directory username is scrubbed
    assert "john_doe" not in snapshot.scan_path
    assert "[redacted]" in snapshot.scan_path


