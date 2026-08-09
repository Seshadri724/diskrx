from typing import List
from dxcli.analyzers.base import AnalyzerPlugin
from dxcli.store.models import DirNode, UnrotatedLog, StaleFile, Prescription


class PostgresWalAnalyzer(AnalyzerPlugin):
    """
    Sample dxcli plugin for Postgres Write-Ahead Logs (WAL).
    """

    @property
    def name(self) -> str:
        return "Postgres WAL Analyzer"

    def analyze(
        self, top_dirs: List[DirNode], logs: List[UnrotatedLog], stales: List[StaleFile]
    ) -> List[Prescription]:
        prescriptions = []
        for d in top_dirs:
            # Look for Postgres WAL directory patterns
            if "pg_wal" in d.path or "pg_xlog" in d.path:
                if d.size_bytes > 5 * (1024**3):  # > 5GB
                    prescriptions.append(
                        Prescription(
                            id="pg_wal_bloat",
                            name="Optimize Postgres WAL retention",
                            template="# Adjust max_wal_size in postgresql.conf\nmax_wal_size = 2GB",
                            risk="safe",
                            size_savings_bytes=d.size_bytes // 2,
                            action_type="instructions",
                            target_path=d.path,
                        )
                    )
        return prescriptions
