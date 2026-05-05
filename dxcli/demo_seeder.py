import os
import time
import shutil
from typing import List
from .store.database import Database
from .store.models import Partition, DirNode

class DemoSeeder:
    def __init__(self, db: Database):
        self.db = db
        self.home = os.path.expanduser("~")
        self.sandbox = os.path.join(self.home, ".dx", "demo_sandbox")
        
    def setup_sandbox(self):
        """Create a physical directory structure for the demo."""
        if os.path.exists(self.sandbox):
            shutil.rmtree(self.sandbox)
        
        os.makedirs(self.sandbox, exist_ok=True)
        
        # Create some directories
        dirs = ["app", "logs", "cache", "temp"]
        for d in dirs:
            os.makedirs(os.path.join(self.sandbox, d), exist_ok=True)
            
        # Create a "stale" file (accessed 45 days ago)
        stale_path = os.path.join(self.sandbox, "temp", "old_session.tmp")
        with open(stale_path, "w") as f:
            f.write("A" * 1024 * 1024 * 50) # 50MB
        
        # Set old access time
        old_time = time.time() - (45 * 86400)
        os.utime(stale_path, (old_time, old_time))
        
        # Create a "log bomb" file
        log_path = os.path.join(self.sandbox, "logs", "production.log")
        # Current log size should be around 15GB (1GB base + 7 days * 2GB)
        # We don't want to actually write 15GB to disk, so we'll use truncate or just a smaller but significant size.
        # Let's use 500MB to be safe but visible.
        with open(log_path, "wb") as f:
            f.truncate(500 * 1024**2) 
            
        return self.sandbox

    def seed_history(self):
        """Seed SQLite with 7 days of growth for the sandbox."""
        # We'll simulate a 100GB partition where the sandbox lives
        partition = Partition(
            device="demo_vdisk",
            mountpoint=self.sandbox,
            fstype="demo",
            total_bytes=100 * 1024**3,
            used_bytes=30 * 1024**3,
            free_bytes=70 * 1024**3
        )
        
        # Growth: Logs dir grows by 2GB/day
        # Other dirs are stable
        start_time = time.time() - (7 * 86400)
        
        base_sizes = {
            os.path.join(self.sandbox, "app"): 5 * 1024**3,
            os.path.join(self.sandbox, "logs"): 1 * 1024**3,
            os.path.join(self.sandbox, "cache"): 2 * 1024**3,
            os.path.join(self.sandbox, "temp"): 500 * 1024**2,
        }
        
        for day in range(8): # 0 to 7 days
            ts = start_time + (day * 86400)
            
            # Increase log size by 2GB per day
            log_size = base_sizes[os.path.join(self.sandbox, "logs")] + (day * 2 * 1024**3)
            
            top_dirs = []
            current_total_used = 0
            for path, base_size in base_sizes.items():
                size = log_size if "logs" in path else base_size
                top_dirs.append(DirNode(path=path, size_bytes=size, file_count=100))
                current_total_used += size
            
            # Update partition usage for this snapshot
            partition.used_bytes = 30 * 1024**3 + (day * 2 * 1024**3)
            
            # Record snapshot manually at specific timestamp
            self._record_snapshot_at_time(partition, top_dirs, ts)

    def _record_snapshot_at_time(self, partition: Partition, top_dirs: List[DirNode], timestamp: float):
        cursor = self.db._conn.cursor()
        cursor.execute(
            "INSERT INTO snapshots (timestamp, mountpoint, total_bytes, used_bytes) VALUES (?, ?, ?, ?)",
            (timestamp, partition.mountpoint, partition.total_bytes, partition.used_bytes)
        )
        snapshot_id = cursor.lastrowid
        
        for d in top_dirs:
            cursor.execute(
                "INSERT INTO directory_metrics (snapshot_id, path, size_bytes, file_count) VALUES (?, ?, ?, ?)",
                (snapshot_id, d.path, d.size_bytes, d.file_count)
            )
        self.db._conn.commit()
