"""Tests for format_bytes utility."""

from dxcli.outputs.cli_report import format_bytes


def test_format_bytes_gb():
    assert format_bytes(2 * 1024**3) == "2.0 GB"


def test_format_bytes_mb():
    assert format_bytes(500 * 1024**2) == "500.0 MB"


def test_format_bytes_kb():
    assert format_bytes(500 * 1024) == "500.0 KB"


def test_format_bytes_b():
    assert format_bytes(42) == "42 B"
