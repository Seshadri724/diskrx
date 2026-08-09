from dxcli.store.models import Partition


def test_partition_usage_percent():
    p = Partition(
        device="test",
        mountpoint="/",
        fstype="ext4",
        total_bytes=1000,
        used_bytes=750,
        free_bytes=250,
    )
    assert p.usage_percent == 75.0

    p_empty = Partition(
        device="test",
        mountpoint="/",
        fstype="ext4",
        total_bytes=0,
        used_bytes=0,
        free_bytes=0,
    )
    assert p_empty.usage_percent == 0.0
