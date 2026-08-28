import io
import json
import sys

import pytest

from dxcli.mcp import McpServer, is_path_allowed


def _run_stdio(server, messages, monkeypatch):
    """Drive run_stdio with messages, returning the parsed stdout responses."""
    monkeypatch.setattr(
        sys, "stdin", io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n")
    )
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    server.run_stdio()
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def test_mcp_path_allowlist(tmp_path):
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    restricted_dir = tmp_path / "restricted"
    restricted_dir.mkdir()

    server = McpServer(allow_paths=[str(allowed_dir)])

    assert is_path_allowed(str(allowed_dir), [str(allowed_dir)]) is True
    res = server.handle_tool_call("disk_status", {"path": str(restricted_dir)})
    assert res["isError"] is True
    assert "Access denied" in res["content"][0]["text"]


def test_mcp_path_allowlist_rejects_symlink_escape(tmp_path):
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    link = allowed_dir / "outside-link"
    try:
        link.symlink_to(outside_dir, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks not supported in this environment")

    assert is_path_allowed(str(link), [str(allowed_dir)]) is False


def test_mcp_diff_rejects_baseline_outside_allowlist(tmp_path):
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    outside_baseline = tmp_path / "outside-baseline.json"
    outside_baseline.write_text("{}", encoding="utf-8")

    server = McpServer(allow_paths=[str(allowed_dir)])
    res = server.handle_tool_call(
        "diff",
        {"path": str(allowed_dir), "baseline_file": str(outside_baseline)},
    )

    assert res["isError"] is True
    assert "baseline file" in res["content"][0]["text"]
    assert "outside allowed directories" in res["content"][0]["text"]


def test_mcp_disk_status_tool(tmp_path):
    server = McpServer(allow_paths=[str(tmp_path)])
    res = server.handle_tool_call("disk_status", {"path": str(tmp_path)})

    assert res["isError"] is False
    assert "Mountpoint" in res["content"][0]["text"]


def test_mcp_diagnose_tool(tmp_path):
    server = McpServer(allow_paths=[str(tmp_path)])
    res = server.handle_tool_call("diagnose", {"path": str(tmp_path), "docker": False})

    assert res["isError"] is False
    data = json.loads(res["content"][0]["text"])
    assert "path" in data
    assert "top_dirs" in data


def test_mcp_clean_preview_tool(tmp_path):
    server = McpServer(allow_paths=[str(tmp_path)])
    res = server.handle_tool_call(
        "clean_preview", {"path": str(tmp_path), "docker": False}
    )

    assert res["isError"] is False
    data = json.loads(res["content"][0]["text"])
    assert data["dry_run"] is True
    assert "targets" in data


def test_mcp_raising_tool_keeps_session_alive(tmp_path, monkeypatch):
    """A tool that raises must not kill the loop or corrupt stdout."""
    server = McpServer(allow_paths=[str(tmp_path)])
    responses = _run_stdio(
        server,
        [
            # path as an int makes os.path handling raise TypeError
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "diagnose", "arguments": {"path": 12345}},
            },
            # the session must still answer afterwards
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ],
        monkeypatch,
    )

    assert [r["id"] for r in responses] == [1, 2]
    assert responses[0]["result"]["isError"] is True
    assert responses[1]["result"]["tools"]


def test_mcp_malformed_json_returns_parse_error(tmp_path, monkeypatch):
    """Malformed input must get -32700 rather than silence."""
    server = McpServer(allow_paths=[str(tmp_path)])
    monkeypatch.setattr(sys, "stdin", io.StringIO("{not valid json\n"))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    server.run_stdio()

    resp = json.loads(out.getvalue())
    assert resp["error"]["code"] == -32700
    assert resp["id"] is None


def test_mcp_tools_do_not_persist_db_snapshots(tmp_path, monkeypatch):
    """MCP calls must be read-only and never write snapshots to the database."""
    from dxcli.store.database import Database

    db_file = tmp_path / "history.db"
    monkeypatch.setenv("DXCLI_HOME", str(tmp_path))

    db = Database(str(db_file))
    cur = db._conn.cursor()
    cur.execute("SELECT COUNT(*) FROM snapshots")
    initial_count = cur.fetchone()[0]
    initial_files = {
        item.name: (item.stat().st_size, item.stat().st_mtime_ns)
        for item in tmp_path.iterdir()
    }

    server = McpServer(allow_paths=[str(tmp_path)])

    # 1. disk_status
    res = server.handle_tool_call("disk_status", {"path": str(tmp_path)})
    assert res["isError"] is False

    # 2. diagnose
    res = server.handle_tool_call("diagnose", {"path": str(tmp_path), "docker": False})
    assert res["isError"] is False

    # 3. predict
    res = server.handle_tool_call("predict", {"path": str(tmp_path)})
    assert res["isError"] is False

    # 4. clean_preview
    res = server.handle_tool_call(
        "clean_preview", {"path": str(tmp_path), "docker": False}
    )
    assert res["isError"] is False

    cur.execute("SELECT COUNT(*) FROM snapshots")
    after_count = cur.fetchone()[0]
    assert after_count == initial_count
    after_files = {
        item.name: (item.stat().st_size, item.stat().st_mtime_ns)
        for item in tmp_path.iterdir()
    }
    assert after_files == initial_files
    db.close()


def test_mcp_predict_without_history_does_not_create_state(tmp_path, monkeypatch):
    """Missing history must not be created as a side effect of MCP prediction."""
    state_dir = tmp_path / "state"
    monkeypatch.setenv("DXCLI_HOME", str(state_dir))

    server = McpServer(allow_paths=[str(tmp_path)])
    result = server.handle_tool_call("predict", {"path": str(tmp_path)})

    assert result["isError"] is False
    assert "Prediction unavailable" in result["content"][0]["text"]
    assert not state_dir.exists()


def test_read_only_database_rejects_writes(tmp_path):
    """Read-only prediction access must not be able to mutate history."""
    from dxcli.store.database import Database, DatabaseError

    db_file = tmp_path / "history.db"
    writable = Database(str(db_file))
    writable.close()

    readonly = Database(str(db_file), read_only=True)
    with pytest.raises(DatabaseError, match="read-only"):
        readonly.prune_old()
    readonly.close()
