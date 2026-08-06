import json
from click.testing import CliRunner
from dxcli.autopsy import (
    AutopsyReport,
    render_markdown,
    run_autopsy,
    save_baseline,
    write_github_summary,
)
from dxcli.cli import cli
from dxcli.store.models import DirNode


def test_save_baseline_creates_valid_json(tmp_path):
    baseline_file = tmp_path / "baseline.json"
    save_baseline(str(tmp_path), str(baseline_file), include_docker=False)

    assert baseline_file.exists()
    with open(baseline_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["schema"] == 1
    assert "dirs" in data
    assert "created_at" in data


def test_run_autopsy_diffs_growth_correctly(tmp_path, monkeypatch):
    baseline_file = tmp_path / "baseline.json"

    # Save initial baseline
    monkeypatch.setattr(
        "dxcli.collectors.dir_tree.DirectoryTreeCollector.scan",
        lambda self, path: [
            DirNode(
                path=str(tmp_path / "build"), size_bytes=10 * 1024**2, file_count=10
            ),
            DirNode(
                path=str(tmp_path / "cache"), size_bytes=50 * 1024**2, file_count=5
            ),
        ],
    )
    save_baseline(str(tmp_path), str(baseline_file), include_docker=False)

    # Post-build: build directory grew by 90MB, cache shrunk by 10MB
    monkeypatch.setattr(
        "dxcli.collectors.dir_tree.DirectoryTreeCollector.scan",
        lambda self, path: [
            DirNode(
                path=str(tmp_path / "build"), size_bytes=100 * 1024**2, file_count=50
            ),
            DirNode(
                path=str(tmp_path / "cache"), size_bytes=40 * 1024**2, file_count=4
            ),
        ],
    )

    report = run_autopsy(str(baseline_file), str(tmp_path))

    assert isinstance(report, AutopsyReport)
    assert report.total_growth_bytes == 90 * 1024**2
    assert len(report.grown_dirs) == 1
    assert report.grown_dirs[0].delta_bytes == 90 * 1024**2
    assert "build" in report.probable_cause


def test_run_autopsy_unsupported_schema(tmp_path):
    baseline_file = tmp_path / "future_baseline.json"
    future_data = {"schema": 999, "dirs": []}
    with open(baseline_file, "w") as f:
        json.dump(future_data, f)

    try:
        run_autopsy(str(baseline_file), str(tmp_path))
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unsupported baseline schema version" in str(e)


def test_render_markdown_format(tmp_path, monkeypatch):
    baseline_file = tmp_path / "baseline.json"
    save_baseline(str(tmp_path), str(baseline_file), include_docker=False)
    report = run_autopsy(str(baseline_file), str(tmp_path))

    md = render_markdown(report)
    assert "<!-- dxcli-autopsy -->" in md
    assert "## 🔍 dxcli CI Storage Autopsy Report" in md


def test_write_github_summary(tmp_path, monkeypatch):
    summary_file = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

    wrote = write_github_summary("## Test Summary")
    assert wrote is True
    assert summary_file.exists()
    assert "## Test Summary" in summary_file.read_text(encoding="utf-8")


def test_cli_snapshot_baseline_and_autopsy(tmp_path):
    runner = CliRunner()
    baseline_file = tmp_path / "ci_baseline.json"

    # Step 1: snapshot-baseline
    res1 = runner.invoke(
        cli,
        ["snapshot-baseline", "--baseline", str(baseline_file), str(tmp_path)],
    )
    assert res1.exit_code == 0
    assert baseline_file.exists()

    # Step 2: autopsy
    res2 = runner.invoke(
        cli,
        ["autopsy", "--baseline", str(baseline_file), str(tmp_path)],
    )
    assert res2.exit_code == 0
    assert "dxcli CI Storage Autopsy Report" in res2.output


def test_post_github_pr_comment_missing_token(monkeypatch):
    from dxcli.autopsy import post_github_pr_comment

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert post_github_pr_comment("## Report") is False


def test_post_github_pr_comment_mocked(monkeypatch):
    from dxcli.autopsy import post_github_pr_comment

    monkeypatch.setenv("GITHUB_TOKEN", "fake_token_123")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/42/merge")

    class DummyResponse:
        status = 201

        def read(self):
            return b"[]"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def dummy_urlopen(req, timeout=10):
        return DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", dummy_urlopen)

    assert post_github_pr_comment("<!-- dxcli-autopsy -->\n## Report") is True
