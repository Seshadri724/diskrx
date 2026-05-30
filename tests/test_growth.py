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


def test_predictor_confidence_bands(mocker):
    from dxcli.analyzers.predictor import DiskPredictor
    from dxcli.store.models import Partition
    
    mock_db = mocker.Mock(spec=Database)
    
    # Generate synthetic history with known growth rate and noise
    np.random.seed(42)
    now = time.time()
    
    timestamps = np.array([now - (20 - i) * 3600 for i in range(20)])
    true_slope = 10.0 * (1024**3) / 86400.0  # bytes per second
    base_size = 50.0 * (1024**3)
    
    noise = np.random.normal(0, 10 * (1024**2), 20)  # 10 MB noise std
    sizes = base_size + true_slope * (timestamps - timestamps[0]) + noise
    
    history = [
        {'timestamp': ts, 'used_bytes': int(sz), 'total_bytes': 100 * (1024**3)}
        for ts, sz in zip(timestamps, sizes)
    ]
    
    mock_db.get_history.return_value = history
    
    final_used = int(sizes[-1])
    p = Partition(device="dev", mountpoint="/", fstype="ext4", total_bytes=100 * (1024**3), used_bytes=final_used, free_bytes=100 * (1024**3) - final_used)
    
    predictor = DiskPredictor(mock_db)
    result = predictor.predict_full_date(p)
    
    assert result.days_until_full is not None
    assert result.days_until_full_low is not None
    assert result.days_until_full_high is not None
    assert result.days_until_full_low <= result.days_until_full
    assert result.days_until_full <= result.days_until_full_high

