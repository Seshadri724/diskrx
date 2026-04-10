import pytest
import numpy as np
import time
from dxcli.analyzers.growth import GrowthTracker
from dxcli.store.database import Database

@pytest.fixture
def mock_db(mocker):
    # Mock database to return synthetic history
    return mocker.Mock(spec=Database)

def test_get_growth_rate_linear(mock_db):
    tracker = GrowthTracker(mock_db)
    
    # Simulate linear growth: 100 bytes every 10 seconds (864,000 bytes per day)
    now = time.time()
    mock_db.get_dir_history.return_value = [
        {'timestamp': now - 30, 'size_bytes': 1000},
        {'timestamp': now - 20, 'size_bytes': 1100},
        {'timestamp': now - 10, 'size_bytes': 1200},
        {'timestamp': now,      'size_bytes': 1300},
    ]
    
    rate = tracker.get_growth_rate("/test")
    # m = (300 bytes / 30 seconds) = 10 bytes/sec
    # bytes_per_day = 10 * 86400 = 864000
    assert rate.bytes_per_day == pytest.approx(864000.0)

def test_get_partition_growth_rate(mock_db):
    tracker = GrowthTracker(mock_db)
    
    now = time.time()
    mock_db.get_history.return_value = [
        {'timestamp': now - 10, 'used_bytes': 5000},
        {'timestamp': now,      'used_bytes': 6000},
    ]
    
    velocity = tracker.get_partition_growth_rate("/")
    # (1000 bytes / 10 seconds) * 86400 = 8640000
    assert velocity == pytest.approx(8640000.0)
