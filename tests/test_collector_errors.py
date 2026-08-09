from dxcli.collectors.dir_tree import DirectoryTreeCollector
from dxcli.collectors.docker import DockerCollector
from dxcli.engine import run_diagnosis
from dxcli.store.models import CollectorError, DiagnosticSnapshot


def test_collector_error_fields():
    err = CollectorError(
        collector="directory_tree",
        message="Permission denied",
        path="/root/secret",
        error_type="permission_denied",
        partial=True,
    )
    assert err.collector == "directory_tree"
    assert err.message == "Permission denied"
    assert err.path == "/root/secret"
    assert err.error_type == "permission_denied"
    assert err.partial is True


def test_dir_tree_collector_captures_root_permission_error(tmp_path, monkeypatch):
    def fake_scandir(path):
        raise PermissionError("Access is denied")

    monkeypatch.setattr("os.scandir", fake_scandir)
    collector = DirectoryTreeCollector()
    results = collector.scan(str(tmp_path))

    assert results == []
    assert len(collector.last_errors) == 1
    err = collector.last_errors[0]
    assert err.collector == "directory_tree"
    assert err.error_type == "permission_denied"
    assert "Cannot read root path" in err.message


def test_docker_collector_captures_unavailable_error(monkeypatch):
    collector = DockerCollector()
    monkeypatch.setattr(collector, "is_docker_available", lambda: False)
    result = collector.get_system_df()

    assert result is None
    assert len(collector.last_errors) == 1
    err = collector.last_errors[0]
    assert err.collector == "docker"
    assert err.error_type == "docker_unavailable"


def test_run_diagnosis_aggregates_collector_errors(tmp_path, monkeypatch):
    def fake_scandir(path):
        raise PermissionError("Denied")

    monkeypatch.setattr("os.scandir", fake_scandir)
    snap = run_diagnosis(str(tmp_path))

    assert isinstance(snap, DiagnosticSnapshot)
    assert len(snap.collector_errors) >= 1
    assert any(e.collector == "directory_tree" for e in snap.collector_errors)
