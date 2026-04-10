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
