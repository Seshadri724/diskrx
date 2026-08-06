from dxcli.analyzers.correlation import CorrelationEngine
from dxcli.collectors.process_mapper import ProcessRef


def test_correlation_logic(mocker):
    # Mock the mapper to return a fake culprit
    mock_mapper = mocker.patch("dxcli.analyzers.correlation.ProcessMapper")
    instance = mock_mapper.return_value
    instance.find_culprits.return_value = [
        ProcessRef(pid=123, name="culprit_proc", cmdline=[])
    ]

    engine = CorrelationEngine()

    # Simulate RootCause data
    trends = [
        {"path": "/growing/path", "trend": "Growing ↗", "velocity_per_day": 1000000},
        {"path": "/stable/path", "trend": "Stable", "velocity_per_day": 0},
    ]

    results = engine.correlate(trends)

    # /growing/path should have a culprit
    assert results[0]["culprit"].pid == 123
    assert results[0]["culprit"].name == "culprit_proc"

    # /stable/path should NOT have a culprit (optimization)
    assert results[1]["culprit"] is None


def test_correlation_high_confidence(mocker):
    # Mock mapper and os.path.exists, os.path.getsize
    mock_mapper = mocker.patch("dxcli.analyzers.correlation.ProcessMapper")
    instance = mock_mapper.return_value
    instance.find_culprits.return_value = [
        ProcessRef(
            pid=123,
            name="culprit_proc",
            cmdline=[],
            mode="write",
            files=["/growing/path/file.log"],
        )
    ]

    mocker.patch("os.path.exists", return_value=True)
    # Return 100 on first call, 200 on second call
    mocker.patch("os.path.getsize", side_effect=[100, 200])

    engine = CorrelationEngine()
    trends = [
        {"path": "/growing/path", "trend": "Growing ↗", "velocity_per_day": 1000000}
    ]

    results = engine.correlate(trends)
    assert results[0]["culprit"].pid == 123
    assert results[0]["confidence"] == "High"
