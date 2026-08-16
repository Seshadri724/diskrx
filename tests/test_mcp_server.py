import io
import json
import sys

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
