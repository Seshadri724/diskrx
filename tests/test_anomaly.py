import pytest
from dxcli.analyzers.anomaly import StatisticalAnomalyDetector

def test_log_bomb_detection(mocker):
    mock_db = mocker.Mock()
    # Simulate a sudden 100MB jump after 10KB increments
    now = 1000
    mock_db.get_dir_history.return_value = [
        {'timestamp': now - 40, 'size_bytes': 10000},
        {'timestamp': now - 30, 'size_bytes': 20000},
        {'timestamp': now - 20, 'size_bytes': 30000},
        {'timestamp': now - 10, 'size_bytes': 40000},
        {'timestamp': now,      'size_bytes': 40000 + (100 * 1024 * 1024)} # +100MB
    ]
    
    detector = StatisticalAnomalyDetector(mock_db)
    result = detector.check_for_anomalies("/path")
    assert "LOG BOMB" in result

def test_leak_detection(mocker):
    mock_db = mocker.Mock()
    # Simulate steady 1MB growth every snapshot with no drops
    now = 1000
    mock_db.get_dir_history.return_value = [
        {'timestamp': now - 40, 'size_bytes': 10 * 1024 * 1024},
        {'timestamp': now - 30, 'size_bytes': 11 * 1024 * 1024},
        {'timestamp': now - 20, 'size_bytes': 12 * 1024 * 1024},
        {'timestamp': now - 10, 'size_bytes': 13 * 1024 * 1024},
        {'timestamp': now,      'size_bytes': 14 * 1024 * 1024}
    ]
    
    detector = StatisticalAnomalyDetector(mock_db)
    result = detector.check_for_anomalies("/path")
    assert "LEAK" in result
