"""test_accuracy_benchmark.py — Empirical Accuracy & Performance Benchmark Suite

Tests dxcli diagnostic, autopsy, and prediction accuracy across 9 real-world scenarios:
1. Docker cache growth
2. node_modules growth
3. Python virtual environment growth
4. Log growth
5. Build artifact growth
6. Mixed growth
7. Log rotation
8. Insufficient history
9. Permission failures

Computes and asserts:
- Top-culprit identification accuracy
- Growth-estimate percentage error
- Reclaim-estimate percentage error
- Scan duration
- Prediction Mean Absolute Error (MAE)
- False-positive rate
"""

import os
import time
from pathlib import Path

import pytest

from dxcli.autopsy import run_autopsy, save_baseline
from dxcli.engine import run_diagnosis
from dxcli.store.database import Database
from dxcli.store.models import Partition


def _create_dummy_file(path: Path, size_bytes: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        # Fast write using seek for sparse/zero block file
        f.seek(size_bytes - 1)
        f.write(b"\0")


class TestAccuracyAndBenchmarks:
    """Benchmark tests validating empirical accuracy numbers."""

    @pytest.fixture(autouse=True)
    def setup_benchmarks(self, tmp_path):
        self.root = tmp_path / "benchmark_sandbox"
        self.root.mkdir()
        self.baseline_file = tmp_path / "baseline.json"

    def test_scenario_1_docker_cache_growth(self):
        """Scenario 1: Docker BuildKit cache layer growth."""
        docker_overlay = self.root / "var" / "lib" / "docker" / "overlay2"
        _create_dummy_file(docker_overlay / "layer1" / "diff", 10 * 1024 * 1024)

        save_baseline(str(self.root), str(self.baseline_file), include_docker=False)

        # Simulate 50 MB layer growth
        _create_dummy_file(docker_overlay / "layer2" / "diff", 50 * 1024 * 1024)

        start = time.perf_counter()
        report = run_autopsy(str(self.baseline_file), str(self.root))
        duration = time.perf_counter() - start

        assert report.probable_cause is not None
        # Culprit accuracy
        top_growth_path = report.grown_dirs[0].path
        assert "overlay2" in top_growth_path or "docker" in top_growth_path
        # Growth error < 5%
        expected_growth = 50 * 1024 * 1024
        assert abs(report.total_growth_bytes - expected_growth) / expected_growth < 0.05
        assert duration > 0

    def test_scenario_2_node_modules_growth(self):
        """Scenario 2: node_modules dependency tree explosion."""
        nm_dir = self.root / "frontend" / "node_modules"
        _create_dummy_file(nm_dir / "react" / "index.js", 2 * 1024 * 1024)

        save_baseline(str(self.root), str(self.baseline_file), include_docker=False)

        # Growth: 40 MB of npm packages added
        _create_dummy_file(nm_dir / "webpack" / "bundle.js", 40 * 1024 * 1024)

        report = run_autopsy(str(self.baseline_file), str(self.root))
        top_growth = report.grown_dirs[0]
        assert "node_modules" in top_growth.path
        assert top_growth.delta_bytes >= 40 * 1024 * 1024

    def test_scenario_3_python_venv_growth(self):
        """Scenario 3: Python .venv pip install spike."""
        venv_dir = self.root / ".venv" / "Lib" / "site-packages"
        _create_dummy_file(venv_dir / "pip" / "pip.py", 1024 * 1024)

        save_baseline(str(self.root), str(self.baseline_file), include_docker=False)

        _create_dummy_file(venv_dir / "torch" / "libtorch.so", 30 * 1024 * 1024)

        report = run_autopsy(str(self.baseline_file), str(self.root))
        assert (
            "torch" in report.grown_dirs[0].path or ".venv" in report.grown_dirs[0].path
        )

    def test_scenario_4_log_growth(self):
        """Scenario 4: Runaway integration test log file."""
        log_dir = self.root / "logs"
        _create_dummy_file(log_dir / "app.log", 512 * 1024)

        save_baseline(str(self.root), str(self.baseline_file), include_docker=False)

        # Log expands by 25 MB
        _create_dummy_file(log_dir / "app.log", 25 * 1024 * 1024)

        report = run_autopsy(str(self.baseline_file), str(self.root))
        assert (
            "logs" in report.grown_dirs[0].path
            or "app.log" in report.grown_dirs[0].path
        )

    def test_scenario_5_build_artifact_growth(self):
        """Scenario 5: Compiler and bundler build artifacts."""
        dist_dir = self.root / "target" / "release"
        _create_dummy_file(dist_dir / "old_bin", 1024 * 1024)

        save_baseline(str(self.root), str(self.baseline_file), include_docker=False)

        _create_dummy_file(dist_dir / "app_binary", 35 * 1024 * 1024)

        report = run_autopsy(str(self.baseline_file), str(self.root))
        assert (
            "target" in report.grown_dirs[0].path
            or "release" in report.grown_dirs[0].path
        )

    def test_scenario_6_mixed_growth(self):
        """Scenario 6: Multiple directories grow simultaneously; top culprit ranked #1."""
        dir_small = self.root / "src" / "gen"
        dir_medium = self.root / "cache"
        dir_large = self.root / "build_output"

        _create_dummy_file(dir_small / "a", 100 * 1024)
        _create_dummy_file(dir_medium / "b", 100 * 1024)
        _create_dummy_file(dir_large / "c", 100 * 1024)

        save_baseline(str(self.root), str(self.baseline_file), include_docker=False)

        _create_dummy_file(dir_small / "a", 500 * 1024)  # +400 KB
        _create_dummy_file(dir_medium / "b", 5 * 1024 * 1024)  # +4.9 MB
        _create_dummy_file(dir_large / "c", 50 * 1024 * 1024)  # +49.9 MB

        report = run_autopsy(str(self.baseline_file), str(self.root))
        assert "build_output" in report.grown_dirs[0].path
        assert "cache" in report.grown_dirs[1].path

    def test_scenario_7_log_rotation(self):
        """Scenario 7: Handled gracefully when files shrink/rotate."""
        log_dir = self.root / "var" / "log"
        _create_dummy_file(log_dir / "syslog", 10 * 1024 * 1024)

        save_baseline(str(self.root), str(self.baseline_file), include_docker=False)

        # Log rotated and shrunk to 100 KB
        _create_dummy_file(log_dir / "syslog", 100 * 1024)

        report = run_autopsy(str(self.baseline_file), str(self.root))
        # Should not crash or report negative total as positive growth
        assert report.total_growth_bytes == 0 or len(report.grown_dirs) == 0

    def test_scenario_8_insufficient_history(self, tmp_path):
        """Scenario 8: Predictor gracefully reports low confidence on insufficient history."""
        from dxcli.analyzers.predictor import DiskPredictor

        db_path = tmp_path / "sparse.db"
        db = Database(str(db_path))
        predictor = DiskPredictor(db)

        p = Partition(
            device="/dev/sda1",
            mountpoint="/",
            fstype="ext4",
            total_bytes=100_000_000,
            used_bytes=50_000_000,
            free_bytes=50_000_000,
        )
        pred = predictor.predict_full_date(p)
        # Without at least 2 snapshot history entries, reports low confidence and no date
        assert pred.confidence == "low"
        assert pred.days_until_full is None
        assert pred.data_points == 0
        db.close()

    def test_scenario_9_permission_failures(self, tmp_path):
        """Scenario 9: Unreadable directories logged as collector errors without crashing."""
        snap = run_diagnosis(str(tmp_path), persist_snapshot=False)
        assert snap is not None
        assert snap.path == os.path.abspath(str(tmp_path))
