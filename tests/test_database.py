import pytest
from dxcli.store.database import Database
from dxcli.store.models import Partition, DirNode

@pytest.fixture
def db():
    # Use in-memory for testing
    return Database(":memory:")

def test_record_snapshot(db):
    p = Partition(device="test", mountpoint="/", fstype="ext4", 
                  total_bytes=1000, used_bytes=500, free_bytes=500)
    top_dirs = [DirNode(path="/var/log", size_bytes=100, file_count=5)]
    
    db.record_snapshot(p, top_dirs)
    
    history = db.get_history("/")
    assert len(history) == 1
    assert history[0]['used_bytes'] == 500
    
    dir_history = db.get_dir_history("/var/log")
    assert len(dir_history) == 1
    assert dir_history[0]['size_bytes'] == 100


def test_prune_old(db):
    import time
    
    cur = db._conn.cursor()
    now = time.time()
    for i in range(1000):
        ts = now - (i * 86400)
        cur.execute(
            "INSERT INTO snapshots (timestamp, mountpoint, total_bytes, used_bytes) "
            "VALUES (?, ?, ?, ?)",
            (ts, "/", 1000, 500),
        )
        snapshot_id = cur.lastrowid
        cur.execute(
            "INSERT INTO directory_metrics (snapshot_id, path, size_bytes, file_count) "
            "VALUES (?, ?, ?, ?)",
            (snapshot_id, "/var/log", 100, 5),
        )
    db._conn.commit()
    
    cur.execute("SELECT COUNT(*) FROM snapshots")
    assert cur.fetchone()[0] == 1000
    cur.execute("SELECT COUNT(*) FROM directory_metrics")
    assert cur.fetchone()[0] == 1000
    
    db.prune_old(30)
    
    cur.execute("SELECT COUNT(*) FROM snapshots")
    snap_count = cur.fetchone()[0]
    assert snap_count <= 31
    cur.execute("SELECT COUNT(*) FROM directory_metrics")
    metrics_count = cur.fetchone()[0]
    assert metrics_count == snap_count

