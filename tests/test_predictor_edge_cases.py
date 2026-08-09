import time
import pytest
from dxcli.analyzers.predictor import DiskPredictor
from dxcli.store.database import Database
from dxcli.store.models import Partition


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test.db"
    db = Database(str(db_file))
    yield db
    db.close()


def save_snapshot_at(db: Database, partition: Partition, ts: float):
    db._conn.execute(
        "INSERT INTO snapshots (timestamp, mountpoint, total_bytes, used_bytes) VALUES (?, ?, ?, ?)",
        (ts, partition.mountpoint, partition.total_bytes, partition.used_bytes),
    )
    db._conn.commit()


def test_insufficient_history(temp_db):
    predictor = DiskPredictor(temp_db)
    partition = Partition(
        device="/dev/sda1",
        mountpoint="/",
        fstype="ext4",
        total_bytes=100 * 1024**3,
        used_bytes=50 * 1024**3,
        free_bytes=50 * 1024**3,
    )

    # Insert only 1 snapshot
    save_snapshot_at(temp_db, partition, time.time())
    res = predictor.predict_full_date(partition)

    assert res is not None
    assert res.confidence == "low"
    assert res.hint == "insufficient history"
    assert res.data_points == 1


def test_already_full_disk(temp_db):
    predictor = DiskPredictor(temp_db)
    partition = Partition(
        device="/dev/sda1",
        mountpoint="/",
        fstype="ext4",
        total_bytes=100 * 1024**3,
        used_bytes=100 * 1024**3,
        free_bytes=0,
    )

    res = predictor.predict_full_date(partition)

    assert res is not None
    assert res.days_until_full == 0.0
    assert res.hint == "already full"
    assert res.confidence == "high"


def test_static_disk_zero_growth(temp_db):
    now = time.time()
    partition = Partition(
        device="/dev/sda1",
        mountpoint="/",
        fstype="ext4",
        total_bytes=100 * 1024**3,
        used_bytes=50 * 1024**3,
        free_bytes=50 * 1024**3,
    )

    # Insert static usage snapshots over 5 days
    for i in range(5):
        p = Partition(
            device="/dev/sda1",
            mountpoint="/",
            fstype="ext4",
            total_bytes=100 * 1024**3,
            used_bytes=50 * 1024**3,
            free_bytes=50 * 1024**3,
        )
        save_snapshot_at(temp_db, p, now - (5 - i) * 86400)

    predictor = DiskPredictor(temp_db)
    res = predictor.predict_full_date(partition)

    assert res is not None
    assert res.days_until_full is None
    assert res.hint == "stable"


def test_linear_growth_high_confidence(temp_db):
    now = time.time()
    partition = Partition(
        device="/dev/sda1",
        mountpoint="/",
        fstype="ext4",
        total_bytes=100 * 1024**3,
        used_bytes=60 * 1024**3,
        free_bytes=40 * 1024**3,
    )

    # Perfect 2GB/day linear growth over 6 days
    for i in range(6):
        used = (50 + i * 2) * 1024**3
        p = Partition(
            device="/dev/sda1",
            mountpoint="/",
            fstype="ext4",
            total_bytes=100 * 1024**3,
            used_bytes=used,
            free_bytes=100 * 1024**3 - used,
        )
        save_snapshot_at(temp_db, p, now - (6 - i) * 86400)

    predictor = DiskPredictor(temp_db)
    res = predictor.predict_full_date(partition)

    assert res is not None
    assert res.confidence == "high"
    assert res.r_squared is not None and res.r_squared >= 0.85
    assert res.days_until_full is not None and res.days_until_full > 0


def test_high_variance_growth(temp_db):
    now = time.time()
    partition = Partition(
        device="/dev/sda1",
        mountpoint="/",
        fstype="ext4",
        total_bytes=100 * 1024**3,
        used_bytes=50 * 1024**3,
        free_bytes=50 * 1024**3,
    )

    # Wild fluctuating growth
    usages = [10, 40, 15, 60, 20, 50]
    for i, u in enumerate(usages):
        p = Partition(
            device="/dev/sda1",
            mountpoint="/",
            fstype="ext4",
            total_bytes=100 * 1024**3,
            used_bytes=u * 1024**3,
            free_bytes=(100 - u) * 1024**3,
        )
        save_snapshot_at(temp_db, p, now - (6 - i) * 86400)

    predictor = DiskPredictor(temp_db)
    res = predictor.predict_full_date(partition)

    assert res is not None
    assert res.confidence == "low"


def test_accelerating_growth(temp_db):
    now = time.time()
    partition = Partition(
        device="/dev/sda1",
        mountpoint="/",
        fstype="ext4",
        total_bytes=100 * 1024**3,
        used_bytes=70 * 1024**3,
        free_bytes=30 * 1024**3,
    )

    # Quadratic accelerating growth
    for i in range(7):
        used = (20 + (i**2)) * 1024**3
        p = Partition(
            device="/dev/sda1",
            mountpoint="/",
            fstype="ext4",
            total_bytes=100 * 1024**3,
            used_bytes=used,
            free_bytes=100 * 1024**3 - used,
        )
        save_snapshot_at(temp_db, p, now - (7 - i) * 86400)

    predictor = DiskPredictor(temp_db)
    res = predictor.predict_full_date(partition)

    assert res is not None
    assert res.is_accelerating is True


def test_log_rotation_recent_drop(temp_db):
    now = time.time()
    partition = Partition(
        device="/dev/sda1",
        mountpoint="/",
        fstype="ext4",
        total_bytes=100 * 1024**3,
        used_bytes=30 * 1024**3,
        free_bytes=70 * 1024**3,
    )

    # Steady growth then sudden drop in recent 24h
    history_usages = [40, 50, 60, 70, 30]
    for i, u in enumerate(history_usages):
        p = Partition(
            device="/dev/sda1",
            mountpoint="/",
            fstype="ext4",
            total_bytes=100 * 1024**3,
            used_bytes=u * 1024**3,
            free_bytes=(100 - u) * 1024**3,
        )
        save_snapshot_at(temp_db, p, now - (5 - i) * 10000)

    predictor = DiskPredictor(temp_db)
    res = predictor.predict_full_date(partition)

    assert res is not None
    assert res.hint == "rotated recently"


def test_empty_disk(temp_db):
    partition = Partition(
        device="/dev/sda1",
        mountpoint="/",
        fstype="ext4",
        total_bytes=100 * 1024**3,
        used_bytes=0,
        free_bytes=100 * 1024**3,
    )

    predictor = DiskPredictor(temp_db)
    res = predictor.predict_full_date(partition)

    assert res is not None
    assert res.confidence == "low"


def test_none_partition(temp_db):
    predictor = DiskPredictor(temp_db)
    assert predictor.predict_full_date(None) is None


def test_identical_timestamps(temp_db):
    now = time.time()
    partition = Partition(
        device="/dev/sda1",
        mountpoint="/",
        fstype="ext4",
        total_bytes=100 * 1024**3,
        used_bytes=50 * 1024**3,
        free_bytes=50 * 1024**3,
    )

    for _ in range(4):
        p = Partition(
            device="/dev/sda1",
            mountpoint="/",
            fstype="ext4",
            total_bytes=100 * 1024**3,
            used_bytes=50 * 1024**3,
            free_bytes=50 * 1024**3,
        )
        save_snapshot_at(temp_db, p, now)

    predictor = DiskPredictor(temp_db)
    res = predictor.predict_full_date(partition)

    assert res is not None


def test_terabyte_overflow_safety(temp_db):
    now = time.time()
    partition = Partition(
        device="/dev/sda1",
        mountpoint="/",
        fstype="ext4",
        total_bytes=1000 * 1024**4,
        used_bytes=500 * 1024**4,
        free_bytes=500 * 1024**4,
    )

    # 10 TB per day growth
    for i in range(5):
        used = (100 + i * 100) * 1024**4
        p = Partition(
            device="/dev/sda1",
            mountpoint="/",
            fstype="ext4",
            total_bytes=1000 * 1024**4,
            used_bytes=used,
            free_bytes=1000 * 1024**4 - used,
        )
        save_snapshot_at(temp_db, p, now - (5 - i) * 86400)

    predictor = DiskPredictor(temp_db)
    res = predictor.predict_full_date(partition)

    assert res is not None
    assert res.daily_growth_bytes > 0


def test_database_error_fallback(temp_db, monkeypatch):
    partition = Partition(
        device="/dev/sda1",
        mountpoint="/",
        fstype="ext4",
        total_bytes=100 * 1024**3,
        used_bytes=50 * 1024**3,
        free_bytes=50 * 1024**3,
    )

    def broken_get_history(*args, **kwargs):
        raise RuntimeError("Database connection lost")

    monkeypatch.setattr(temp_db, "get_history", broken_get_history)
    predictor = DiskPredictor(temp_db)

    try:
        predictor.predict_full_date(partition)
    except Exception as exc:
        assert isinstance(exc, RuntimeError)
