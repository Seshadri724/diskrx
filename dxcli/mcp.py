"""Model Context Protocol (MCP) Server for dxcli.

Exposes read-only disk analysis, prediction, diffing, and cleanup preview tools
to AI agents (Claude Code, Claude Desktop, Cursor, etc.) via stdio JSON-RPC 2.0.

Read-only tools exposed:
- disk_status: Query mountpoint capacity, used bytes, free bytes, and usage percent.
- diagnose: Run deep diagnostic scan on path (top directories, logs, stale files, prescriptions).
- diff: Run build storage growth autopsy diff against pre-build baseline snapshot file.
- predict: Query time-to-full prediction and growth acceleration for partition.
- clean_preview: Run dry-run cleanup plan to discover reclaimable caches and build artifacts.

Safety:
- Absolutely ZERO tools perform deletion or state mutations.
- Restricts operations to allowed directory trees (defaulting to cwd and user home).
"""

import json
import logging
import os
import sys
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from . import __version__
from .analyzers.predictor import DiskPredictor
from .autopsy import run_autopsy
from .clean_engine import CleanEngine
from .engine import run_diagnosis
from .outputs.cli_report import format_bytes
from .store.database import Database

logger = logging.getLogger(__name__)


def is_path_allowed(path: str, allow_paths: Optional[List[str]] = None) -> bool:
    """Ensure target path falls within allowed directory boundaries."""
    if not allow_paths:
        allow_paths = [os.getcwd(), os.path.expanduser("~")]

    abs_target = os.path.abspath(path).lower()
    for allowed in allow_paths:
        abs_allowed = os.path.abspath(allowed).lower()
        if abs_target == abs_allowed or abs_target.startswith(abs_allowed + os.sep):
            return True
    return False


TOOLS_MANIFEST = [
    {
        "name": "disk_status",
        "description": "Get storage capacity, used bytes, free space, and usage percentage for a directory or mountpoint.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path or mountpoint to query (default: current directory).",
                    "default": ".",
                }
            },
        },
    },
    {
        "name": "diagnose",
        "description": "Run deep disk intelligence analysis returning top storage-consuming directories, unrotated log files, stale files, policy violations, and cleanup prescriptions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Target directory to diagnose (default: current directory).",
                    "default": ".",
                },
                "docker": {
                    "type": "boolean",
                    "description": "Include Docker disk usage breakdown.",
                    "default": True,
                },
            },
        },
    },
    {
        "name": "diff",
        "description": "Compare current storage against a pre-build baseline snapshot file to identify what grew during a build.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "baseline_file": {
                    "type": "string",
                    "description": "Path to pre-build baseline snapshot JSON file.",
                },
                "path": {
                    "type": "string",
                    "description": "Current directory path to compare (default: current directory).",
                    "default": ".",
                },
            },
            "required": ["baseline_file"],
        },
    },
    {
        "name": "predict",
        "description": "Calculate time-to-full storage prediction, daily growth rate, and prediction confidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Target directory or mountpoint (default: current directory).",
                    "default": ".",
                }
            },
        },
    },
    {
        "name": "clean_preview",
        "description": "Run a dry-run preview of disposable caches, build artifacts, and Docker bloat that can be safely reclaimed. Performs NO deletions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Target directory to scan for disposable artifacts (default: current directory).",
                    "default": ".",
                },
                "docker": {
                    "type": "boolean",
                    "description": "Include Docker reclaimables in preview.",
                    "default": True,
                },
            },
        },
    },
]


class McpServer:
    """Stdio JSON-RPC 2.0 Model Context Protocol server exposing read-only storage tools."""

    def __init__(self, allow_paths: Optional[List[str]] = None):
        self.allow_paths = allow_paths or [os.getcwd(), os.path.expanduser("~")]

    def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute read-only tool and return structured tool result."""
        path = arguments.get("path", ".")

        if not is_path_allowed(path, self.allow_paths):
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Access denied: path '{path}' is outside allowed directories.",
                    }
                ],
                "isError": True,
            }

        if name == "disk_status":
            snap = run_diagnosis(path, include_docker=False, include_processes=False)
            if not snap.partition:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Partition info unavailable for {path}",
                        }
                    ],
                    "isError": True,
                }
            p = snap.partition
            res_text = (
                f"Mountpoint: {p.mountpoint}\n"
                f"Total Capacity: {format_bytes(p.total_bytes)}\n"
                f"Used Space: {format_bytes(p.used_bytes)} ({p.usage_percent:.1f}%)\n"
                f"Free Space: {format_bytes(p.free_bytes)}"
            )
            return {"content": [{"type": "text", "text": res_text}], "isError": False}

        elif name == "diagnose":
            include_docker = arguments.get("docker", True)
            snap = run_diagnosis(path, include_docker=include_docker)
            out = {
                "path": snap.path,
                "partition": asdict(snap.partition) if snap.partition else None,
                "top_dirs": [asdict(d) for d in snap.top_dirs[:10]],
                "unrotated_logs": [asdict(log_item) for log_item in snap.logs],
                "stale_files": [asdict(s) for s in snap.stale_files],
                "prescriptions": [asdict(pr) for pr in snap.prescriptions],
                "collector_errors": [asdict(e) for e in snap.collector_errors],
            }
            return {
                "content": [{"type": "text", "text": json.dumps(out, indent=2)}],
                "isError": False,
            }

        elif name == "diff":
            baseline_file = arguments.get("baseline_file")
            if not baseline_file:
                return {
                    "content": [
                        {"type": "text", "text": "baseline_file parameter required"}
                    ],
                    "isError": True,
                }
            try:
                report = run_autopsy(baseline_file, path)
                out = {
                    "probable_cause": report.probable_cause,
                    "total_growth_bytes": report.total_growth_bytes,
                    "grown_dirs": [asdict(g) for g in report.grown_dirs],
                    "docker_growth": report.docker_growth,
                    "prescriptions": [asdict(pr) for pr in report.prescriptions],
                }
                return {
                    "content": [{"type": "text", "text": json.dumps(out, indent=2)}],
                    "isError": False,
                }
            except Exception as exc:
                return {
                    "content": [{"type": "text", "text": f"Diff failed: {exc}"}],
                    "isError": True,
                }

        elif name == "predict":
            db = Database()
            try:
                predictor = DiskPredictor(db)
                snap = run_diagnosis(
                    path, include_docker=False, include_processes=False
                )
                if not snap.partition:
                    return {
                        "content": [
                            {"type": "text", "text": "Partition info unavailable"}
                        ],
                        "isError": True,
                    }
                pred = predictor.predict_full_date(snap.partition)
                if not pred:
                    return {
                        "content": [{"type": "text", "text": "Prediction unavailable"}],
                        "isError": False,
                    }
                return {
                    "content": [
                        {"type": "text", "text": json.dumps(asdict(pred), indent=2)}
                    ],
                    "isError": False,
                }
            finally:
                db.close()

        elif name == "clean_preview":
            include_docker = arguments.get("docker", True)
            engine = CleanEngine()
            plan = engine.create_plan(path, include_docker=include_docker)
            out = {
                "dry_run": True,
                "scan_path": plan.scan_path,
                "estimated_savings_bytes": plan.estimated_savings_bytes,
                "targets": [asdict(t) for t in plan.targets],
                "protected_excluded": plan.protected_excluded,
            }
            return {
                "content": [{"type": "text", "text": json.dumps(out, indent=2)}],
                "isError": False,
            }

        else:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                "isError": True,
            }

    def run_stdio(self) -> None:
        """Run standard I/O JSON-RPC loop."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError as exc:
                # Never stay silent: a client awaiting a reply would hang.
                resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
                continue

            msg_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params", {})

            if method == "initialize":
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "dxcli", "version": __version__},
                    },
                }
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()

            elif method == "notifications/initialized":
                pass

            elif method == "tools/list":
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"tools": TOOLS_MANIFEST},
                }
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()

            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                try:
                    result = self.handle_tool_call(tool_name, arguments)
                except Exception as exc:
                    # A raising tool must not kill the session or leak a
                    # traceback onto stdout, which is the JSON-RPC channel.
                    logger.exception("Tool %s failed", tool_name)
                    result = {
                        "content": [{"type": "text", "text": f"Tool error: {exc}"}],
                        "isError": True,
                    }
                resp = {"jsonrpc": "2.0", "id": msg_id, "result": result}
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()

            elif msg_id is not None:
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
