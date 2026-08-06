import json

from click.testing import CliRunner

from dxcli.analyzers.predictor import DiskPredictor
from dxcli.collectors.dir_tree import DirectoryTreeCollector
from dxcli.collectors.docker import DockerCollector
from dxcli.cli import cli
from dxcli.store.models import Partition


def test_directory_scan_counts_root_files_and_deep_children(tmp_path):
    direct = tmp_path / "direct.bin"
    direct.write_bytes(b"x" * 17)
    nested = tmp_path / "nested" / "one" / "two" / "three"
    nested.mkdir(parents=True)
    deep_file = nested / "deep.bin"
    deep_file.write_bytes(b"y" * 29)

    results = DirectoryTreeCollector(max_threads=1).scan(str(tmp_path))
    sizes = {item.path: item.size_bytes for item in results}

    assert sizes[str(tmp_path)] == 17
    assert sizes[str(tmp_path / "nested")] == 29


def test_docker_size_parser_accepts_common_units():
    collector = DockerCollector()

    assert collector._parse_size("1.5 GB") == int(1.5 * 1024**3)
    assert collector._parse_size("2GiB") == 2 * 1024**3
    assert collector._parse_size("0B") == 0
    assert collector._parse_size("not-a-size") == 0


def test_predictor_reports_already_full_partition(mocker):
    db = mocker.Mock()
    db.get_history.return_value = []
    partition = Partition("disk", "/", "test", 100, 101, 0)

    result = DiskPredictor(db).predict_full_date(partition)

    assert result.days_until_full == 0.0
    assert result.hint == "already full"


def test_ci_json_preserves_failure_payload(mocker):
    partition = Partition("disk", ".", "test", 100, 95, 5)
    mocker.patch(
        "dxcli.platform.provider.get_partition_for_path", return_value=partition
    )
    mocker.patch(
        "dxcli.collectors.dir_tree.DirectoryTreeCollector.scan", return_value=[]
    )
    mocker.patch("dxcli.collectors.log_finder.LogFinderCollector.scan", return_value=[])
    mocker.patch(
        "dxcli.collectors.stale_files.StaleFileCollector.scan", return_value=[]
    )

    result = CliRunner().invoke(cli, ["diagnose", ".", "--ci", "--json"])

    assert result.exit_code == 4
    payload = json.loads(result.output)
    assert payload["ci_failed"] is True
    assert payload["partition"]["used_bytes"] == 95
