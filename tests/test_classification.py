import os
import pytest
from dxcli.analyzers.classification import ClassificationEngine
from dxcli.store.models import DirNode


def test_classification_summary(tmp_path):
    # Create files with different extensions
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    py_file = code_dir / "app.py"
    py_file.write_text("print('hello')")  # Code

    media_dir = tmp_path / "media"
    media_dir.mkdir()
    jpg_file = media_dir / "photo.jpg"
    jpg_file.write_bytes(b"\xff\xd8\xff\xe0" * 100)  # Media (400 bytes)

    engine = ClassificationEngine()
    summary = engine.get_summary(
        [
            DirNode(path=str(code_dir), size_bytes=14, file_count=1),
            DirNode(path=str(media_dir), size_bytes=400, file_count=1),
        ]
    )

    assert summary["Code"] == 14
    assert summary["Media"] == 400
    assert "Others" in summary


def test_classification_symlink_cycle(tmp_path):
    # Skip symlink tests on Windows if symlink privileges are not available
    cycle_dir = tmp_path / "cycle"
    cycle_dir.mkdir()

    link_path = cycle_dir / "loop"
    try:
        os.symlink(str(cycle_dir), str(link_path), target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are not supported or privileged on this system")

    engine = ClassificationEngine()
    # Scans the cycle_dir. If it follows symlinks, it will loop infinitely.
    # If it skips/handles symlinks, it should terminate immediately.
    res = engine.classify_directory(str(cycle_dir))
    assert isinstance(res, dict)
