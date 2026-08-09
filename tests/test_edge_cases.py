"""Edge case tests for format_bytes, database, and growth tracker."""

from dxcli.outputs.cli_report import format_bytes
from dxcli.store.database import Database
from dxcli.store.models import Partition, DirNode
from dxcli.analyzers.growth import GrowthTracker
from dxcli.outputs.tui import sparkline_str

# --- format_bytes edge cases ---


def test_format_bytes_zero():
    assert format_bytes(0) == "0 B"


def test_format_bytes_negative():
    assert format_bytes(-1024) == "-1.0 KB"


def test_format_bytes_exactly_1gb():
    assert format_bytes(1024**3) == "1.0 GB"


def test_format_bytes_exactly_1mb():
    assert format_bytes(1024**2) == "1.0 MB"


def test_format_bytes_exactly_1kb():
    assert format_bytes(1024) == "1.0 KB"


# --- sparkline_str edge cases ---


def test_sparkline_empty():
    assert sparkline_str([]) == "—"


def test_sparkline_single_value():
    assert sparkline_str([100]) == "—"


def test_sparkline_flat_values():
    result = sparkline_str([100, 100, 100, 100])
    assert len(result) == 4  # Should render flat


def test_sparkline_rising():
    result = sparkline_str([0, 25, 50, 75, 100])
    assert len(result) == 5
    # Last char should be the tallest block
    assert result[-1] == "█"


# --- Database edge cases ---


def test_database_empty_history():
    db = Database(":memory:")
    history = db.get_history("/nonexistent")
    assert history == []


def test_database_empty_dir_history():
    db = Database(":memory:")
    history = db.get_dir_history("/nonexistent")
    assert history == []


def test_database_multiple_snapshots():
    db = Database(":memory:")
    p = Partition(
        device="test",
        mountpoint="/",
        fstype="ext4",
        total_bytes=1000,
        used_bytes=500,
        free_bytes=500,
    )
    dirs1 = [DirNode(path="/var/log", size_bytes=100, file_count=5)]
    dirs2 = [DirNode(path="/var/log", size_bytes=200, file_count=10)]

    db.record_snapshot(p, dirs1)
    db.record_snapshot(p, dirs2)

    history = db.get_history("/")
    assert len(history) == 2

    dir_history = db.get_dir_history("/var/log")
    assert len(dir_history) == 2
    sizes = {d["size_bytes"] for d in dir_history}
    assert sizes == {100, 200}


# --- Growth tracker with identical timestamps ---


def test_growth_tracker_identical_timestamps(mocker):
    """numpy.polyfit with identical x-values should not crash."""
    import time

    mock_db = mocker.Mock(spec=Database)
    tracker = GrowthTracker(mock_db)

    now = time.time()
    mock_db.get_dir_history.return_value = [
        {"timestamp": now, "size_bytes": 1000},
        {"timestamp": now, "size_bytes": 2000},  # Same timestamp!
    ]

    # This should not raise - numpy may warn but shouldn't crash
    tracker.get_growth_rate("/test")
    # Result may be None or have unusual values, but shouldn't throw
