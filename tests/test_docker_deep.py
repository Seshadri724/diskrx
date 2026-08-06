from dxcli.analyzers.docker_analyzer import DockerAnalyzer
from dxcli.collectors.docker import DockerCollector


def test_docker_volume_classification():
    collector = DockerCollector()

    assert collector._parse_size("1.5 GB") == 1610612736
    assert collector._parse_size("500MB") == 524288000


def test_docker_analyzer_named_volume_protection():
    analyzer = DockerAnalyzer()
    df_data = {
        "Images": {"Reclaimable": 600 * 1024 * 1024},
        "Build Cache": {"Reclaimable": 700 * 1024 * 1024},
        "Local Volumes": {"Reclaimable": 800 * 1024 * 1024},
        "Containers": {"Reclaimable": 600 * 1024 * 1024},
    }

    volumes_info = [
        {"name": "a" * 64, "is_anonymous": True, "is_protected": False},
        {
            "name": "production_postgres_data",
            "is_anonymous": False,
            "is_protected": True,
        },
    ]

    prescriptions = analyzer.analyze(df_data, volumes_info=volumes_info)

    # Check for protection prescription
    protected_prescs = [
        p for p in prescriptions if p.id == "docker_named_volumes_protected"
    ]
    assert len(protected_prescs) == 1
    assert "protected from automatic deletion" in protected_prescs[0].description
    assert protected_prescs[0].risk == "needs-review"

    # Check that volume prune command adds safety filter
    vol_prescs = [p for p in prescriptions if p.id == "docker_volumes"]
    assert len(vol_prescs) == 1
    assert "--filter" in vol_prescs[0].template


def test_docker_analyzer_handles_empty_data():
    analyzer = DockerAnalyzer()
    assert analyzer.analyze({}) == []
