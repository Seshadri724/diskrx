import sqlite3
import os
import time
import logging
from typing import List, Dict, Optional

from ..store.models import Partition, DirNode

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Raised when a critical database operation fails."""


class Database:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            from ..state import get_state_dir  # BUG-3 FIX: was `.state` (wrong level)

            db_path = os.path.join(get_state_dir(), "history.db")

        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        # Use a timeout to handle concurrent access gracefully
        self._conn = sqlite3.connect(self.db_path, timeout=10.0)
        self._configure_connection()
        self._init_db()

    def _configure_connection(self) -> None:
        """Apply production-safe SQLite pragmas."""
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=5000")

        # Restrict permissions on the database file (Unix only)
        if os.name != "nt" and os.path.exists(self.db_path):
            try:
                os.chmod(self.db_path, 0o600)
            except OSError:
                pass

    def _init_db(self) -> None:
        cur = self._conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                mountpoint TEXT,
                total_bytes INTEGER,
                used_bytes INTEGER
            )
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS directory_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER,
                path TEXT,
                size_bytes INTEGER,
                file_count INTEGER,
                FOREIGN KEY(snapshot_id) REFERENCES snapshots(id)
            )
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_mount_ts
            ON snapshots(mountpoint, timestamp)
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_dirmetrics_path
            ON directory_metrics(path)
            """)
        self._conn.commit()

    def record_snapshot(self, partition: Partition, top_dirs: List[DirNode]) -> None:
        """Save a disk usage snapshot.

        Raises DatabaseError if the write fails so callers know the snapshot
        was not recorded, rather than silently continuing.
        """
        timestamp = time.time()
        cur = self._conn.cursor()
        try:
            cur.execute(
                "INSERT INTO snapshots (timestamp, mountpoint, total_bytes, used_bytes) "
                "VALUES (?, ?, ?, ?)",
                (
                    timestamp,
                    partition.mountpoint,
                    partition.total_bytes,
                    partition.used_bytes,
                ),
            )
            snapshot_id = cur.lastrowid
            for d in top_dirs:
                cur.execute(
                    "INSERT INTO directory_metrics (snapshot_id, path, size_bytes, file_count) "
                    "VALUES (?, ?, ?, ?)",
                    (snapshot_id, d.path, d.size_bytes, getattr(d, "file_count", 0)),
                )
            self._conn.commit()
            if snapshot_id and snapshot_id % 100 == 0:
                try:
                    self.prune_old()
                except Exception as prune_err:
                    logger.warning("Auto-pruning failed: %s", prune_err)
        except sqlite3.OperationalError as e:
            logger.error("Snapshot write failed: %s", e)
            try:
                self._conn.rollback()
            except Exception:
                pass
            raise DatabaseError(f"Snapshot write failed: {e}") from e

    def get_history(
        self, mountpoint: str, days_back: int = 30, limit: int = 100
    ) -> List[Dict]:
        """Return ordered historical snapshots for a mountpoint."""
        cutoff = time.time() - (days_back * 86400)
        try:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT timestamp, mountpoint, total_bytes, used_bytes FROM snapshots "
                "WHERE mountpoint = ? AND timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
                (mountpoint, cutoff, limit),
            )
            columns = ["timestamp", "mountpoint", "total_bytes", "used_bytes"]
            results = [dict(zip(columns, row)) for row in cur.fetchall()]
            results.reverse()
            return results
        except sqlite3.Error as e:
            logger.error("get_history query failed: %s", e)
            return []

    def get_dir_history(
        self, path: str, days_back: int = 30, limit: int = 100
    ) -> List[Dict]:
        """Return ordered historical size metrics for a specific directory."""
        cutoff = time.time() - (days_back * 86400)
        try:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT s.timestamp, d.size_bytes
                FROM directory_metrics d
                JOIN snapshots s ON s.id = d.snapshot_id
                WHERE d.path = ? AND s.timestamp >= ?
                ORDER BY s.timestamp DESC LIMIT ?
                """,
                (path, cutoff, limit),
            )
            columns = ["timestamp", "size_bytes"]
            results = [dict(zip(columns, row)) for row in cur.fetchall()]
            results.reverse()
            return results
        except sqlite3.Error as e:
            logger.error("get_dir_history query failed: %s", e)
            return []

    def get_snapshot_closest_to(
        self, mountpoint: str, target_timestamp: float
    ) -> Optional[Dict]:
        """Return the snapshot and directory metrics closest to target_timestamp."""
        try:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT id, timestamp FROM snapshots "
                "WHERE mountpoint = ? ORDER BY ABS(timestamp - ?) ASC LIMIT 1",
                (mountpoint, target_timestamp),
            )
            row = cur.fetchone()
            if not row:
                return None

            snapshot_id, ts = row
            cur.execute(
                "SELECT path, size_bytes FROM directory_metrics WHERE snapshot_id = ?",
                (snapshot_id,),
            )
            metrics = {r[0]: r[1] for r in cur.fetchall()}
            return {"snapshot_id": snapshot_id, "timestamp": ts, "metrics": metrics}
        except sqlite3.Error as e:
            logger.error("get_snapshot_closest_to query failed: %s", e)
            return None

    def prune_old(self, days: int = 90) -> None:
        """Delete snapshots and directory metrics older than the specified days, then vacuum."""
        cutoff = time.time() - (days * 86400)
        cur = self._conn.cursor()
        try:
            cur.execute(
                """
                DELETE FROM directory_metrics
                WHERE snapshot_id IN (SELECT id FROM snapshots WHERE timestamp < ?)
                """,
                (cutoff,),
            )
            cur.execute("DELETE FROM snapshots WHERE timestamp < ?", (cutoff,))
            self._conn.commit()
            cur.execute("VACUUM")
            self._conn.commit()
        except sqlite3.Error as e:
            logger.error("prune_old failed: %s", e)
            try:
                self._conn.rollback()
            except Exception:
                pass
            raise DatabaseError(f"Prune failed: {e}") from e

    def close(self) -> None:
        """Close the database connection idempotently."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            finally:
                self._conn = None
