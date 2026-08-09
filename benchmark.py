import os
import time
import sys
from dxcli.collectors.dir_tree import DirectoryTreeCollector


def bench_os_walk(path):
    total_size = 0
    total_count = 0
    start = time.perf_counter()
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
                    total_count += 1
            except OSError:
                pass
    duration = time.perf_counter() - start
    return duration, total_size, total_count


def bench_dxcli(path):
    collector = DirectoryTreeCollector(max_threads=64)
    start = time.perf_counter()
    nodes = collector.scan(path)
    duration = time.perf_counter() - start

    total_size = sum(n.size_bytes for n in nodes)
    total_count = sum(n.file_count for n in nodes)
    return duration, total_size, total_count


if __name__ == "__main__":
    target_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    )
    print(f"Benchmarking path: {target_path}")

    # Run a warmup
    bench_os_walk(target_path)
    # bench_dxcli(target_path)

    print("\n--- os.walk (Standard Python) ---")
    w_dur, w_size, w_count = bench_os_walk(target_path)
    print(f"Time:  {w_dur:.4f} seconds")
    print(f"Files: {w_count}")
    print(f"Size:  {w_size / (1024*1024):.2f} MB")
    print(f"Speed: {w_count / w_dur:.0f} files/sec")

    print("\n--- dxcli Dyson-Scanner (Parallel BFS) ---")
    d_dur, d_size, d_count = bench_dxcli(target_path)
    print(f"Time:  {d_dur:.4f} seconds")
    print(f"Files: {d_count}")
    print(f"Size:  {d_size / (1024*1024):.2f} MB")
    print(f"Speed: {d_count / d_dur:.0f} files/sec")

    if d_dur > 0 and w_dur > 0:
        multiplier = w_dur / d_dur
        print(
            f"\nResult: dxcli is {multiplier:.2f}x faster than standard Python os.walk"
        )
