import sqlite3
import os
import time
from typing import List, Dict, Optional
from ..store.models import Partition, DirNode

class Database:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            home = os.path.expanduser("~")
            dx_dir = os.path.join(home, ".dx")
            os.makedirs(dx_dir, exist_ok=True)
            db_path = os.path.join(dx_dir, "history.db")
            
        self.db_path = db_path
        # Single persistent connection for the lifetime of the instance
        self._conn = sqlite3.connect(self.db_path)
        self._init_db()

    def _get_conn(self):
        return self._conn

    def _init_db(self):
        cursor = self._conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                mountpoint TEXT,
                total_bytes INTEGER,
                used_bytes INTEGER
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS directory_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER,
                path TEXT,
                size_bytes INTEGER,
                file_count INTEGER,
                FOREIGN KEY(snapshot_id) REFERENCES snapshots(id)
            )
        """)
        # Index for faster history lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_mount_ts 
            ON snapshots(mountpoint, timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_dirmetrics_path 
            ON directory_metrics(path)
        """)
        self._conn.commit()

    def record_snapshot(self, partition: Partition, top_dirs: List[DirNode]):
        """Saves a disk usage snapshot for prediction engine."""
        timestamp = time.time()
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO snapshots (timestamp, mountpoint, total_bytes, used_bytes) VALUES (?, ?, ?, ?)",
                (timestamp, partition.mountpoint, partition.total_bytes, partition.used_bytes)
            )
            snapshot_id = cursor.lastrowid
            
            for d in top_dirs:
                cursor.execute(
                    "INSERT INTO directory_metrics (snapshot_id, path, size_bytes, file_count) VALUES (?, ?, ?, ?)",
                    (snapshot_id, d.path, d.size_bytes, getattr(d, 'file_count', 0))
                )
            self._conn.commit()
        except sqlite3.OperationalError as e:
            # Handle disk-full or locked database gracefully
            try:
                self._conn.rollback()
            except Exception:
                pass

    def get_history(self, mountpoint: str, days_back: int = 30, limit: int = 100) -> List[Dict]:
        """Returns ordered historical snapshots for a mountpoint."""
        cutoff = time.time() - (days_back * 86400)
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT timestamp, mountpoint, total_bytes, used_bytes FROM snapshots "
            "WHERE mountpoint = ? AND timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
            (mountpoint, cutoff, limit)
        )
        columns = ['timestamp', 'mountpoint', 'total_bytes', 'used_bytes']
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        results.reverse()
        return results

    def get_dir_history(self, path: str, days_back: int = 30, limit: int = 100) -> List[Dict]:
        """Returns ordered historical size metrics for a specific directory."""
        cutoff = time.time() - (days_back * 86400)
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT s.timestamp, d.size_bytes 
            FROM directory_metrics d
            JOIN snapshots s ON s.id = d.snapshot_id
            WHERE d.path = ? AND s.timestamp >= ?
            ORDER BY s.timestamp DESC LIMIT ?
        """, (path, cutoff, limit))
        columns = ['timestamp', 'size_bytes']
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        results.reverse()
        return results

    def get_snapshot_closest_to(self, mountpoint: str, target_timestamp: float) -> Optional[Dict]:
        """Returns the snapshot ID and directory metrics closest to the target timestamp."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT id, timestamp FROM snapshots "
            "WHERE mountpoint = ? ORDER BY ABS(timestamp - ?) ASC LIMIT 1",
            (mountpoint, target_timestamp)
        )
        row = cursor.fetchone()
        if not row:
            return None
            
        snapshot_id, ts = row
        cursor.execute(
            "SELECT path, size_bytes FROM directory_metrics WHERE snapshot_id = ?",
            (snapshot_id,)
        )
        metrics = {row[0]: row[1] for row in cursor.fetchall()}
        return {"snapshot_id": snapshot_id, "timestamp": ts, "metrics": metrics}

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
