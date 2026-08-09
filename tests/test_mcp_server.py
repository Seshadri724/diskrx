import json
from dxcli.mcp import McpServer, is_path_allowed


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
