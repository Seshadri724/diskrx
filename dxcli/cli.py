import click
import os
from rich.console import Console

console = Console()

@click.group(invoke_without_command=True)
@click.version_option(version="0.1.0", prog_name="dxcli")
@click.pass_context
def cli(ctx):
    """dxcli — The Disk Doctor. Run with no arguments for instant diagnosis."""
    if ctx.invoked_subcommand is None:
        # Default: run diagnose on current directory
        ctx.invoke(diagnose, path='.')

@cli.command()
def status():
    """Show basic disk status for all partitions."""
    from .platform import provider
    
    console.print(f"[bold blue]Disk Status[/bold blue]")
    try:
        partitions = provider.get_partitions()
        for p in partitions:
            width = 20
            filled = int((p.usage_percent / 100) * width)
            bar = ("█" * filled) + ("░" * (width - filled))
            
            gb_total = p.total_bytes / (1024**3)
            gb_used = p.used_bytes / (1024**3)
            
            console.print(f"  {p.mountpoint:<12} {bar} {p.usage_percent:5.1f}%  used {gb_used:.1f}GB / {gb_total:.1f}GB")
    except Exception as e:
        console.print(f"[red]Error fetching partitions: {e}[/red]")

@cli.command()
@click.argument('path', default='.')
def diagnose(path):
    """Perform a deep scan & diagnostic of the path."""
    from .platform import provider
    from .collectors.dir_tree import DirectoryTreeCollector
    from .collectors.log_finder import LogFinderCollector
    from .collectors.stale_files import StaleFileCollector
    from .outputs.cli_report import render_diagnosis
    from .store.database import Database
    from .analyzers import PrescriptionEngine, RootCauseAnalyzer, CorrelationEngine, AnomalyDetector, DiskPredictor

    path = os.path.abspath(path)
    console.print(f"[dim]Scanning {path}...[/dim]", end="\r")
    
    # 1. Get partition info
    partition = None
    try:
        parts = provider.get_partitions()
        for p in parts:
            p_mount = p.mountpoint.lower() if os.name == 'nt' else p.mountpoint
            path_norm = path.lower() if os.name == 'nt' else path
            if path_norm.startswith(p_mount):
                partition = p
    except Exception:
        pass
        
    # 2. Run collectors
    dir_collector = DirectoryTreeCollector()
    top_dirs = dir_collector.scan(path)
    
    log_collector = LogFinderCollector()
    logs = log_collector.scan([path])
    
    stale_collector = StaleFileCollector()
    stales = stale_collector.scan([path])
    
    # 3. Save Snapshot (single db instance)
    db = Database()
    if partition:
        db.record_snapshot(partition, top_dirs)

    # 4. Analyze Root Cause & Trends
    rca = RootCauseAnalyzer(db)
    trends = rca.attribute_cause(top_dirs)

    # 5. Correlate with processes
    correlator = CorrelationEngine()
    correlated_trends = correlator.correlate(trends)
    
    # 6. Attach history arrays to each trend for sparklines
    for t in correlated_trends:
        h = db.get_dir_history(t['path'], limit=10)
        t['history'] = [entry['size_bytes'] for entry in h]

    # 7. Detect anomalies
    detector = AnomalyDetector(db)
    anomalies = []
    for d in top_dirs[:5]:
        res = detector.check_for_anomalies(d.path)
        if res:
            anomalies.append(res)

    # 8. Predict time-to-full
    prediction = None
    if partition:
        predictor = DiskPredictor(db)
        prediction = predictor.predict_full_date(partition)

    # 9. Synthesize Prescriptions
    engine = PrescriptionEngine()
    prescriptions = engine.synthesize(logs, stales)

    db.close()

    # 10. Present the marketing screenshot
    render_diagnosis(path, partition, top_dirs, logs, stales,
                     trends=correlated_trends, prescriptions=prescriptions,
                     anomalies=anomalies, prediction=prediction)

@cli.command()
@click.argument('path', default='.')
def predict(path):
    """Predict when a disk will become full based on history."""
    from .platform import provider
    from .store.database import Database
    from .analyzers import DiskPredictor
    
    path = os.path.abspath(path)
    
    partition = None
    try:
        parts = provider.get_partitions()
        for p in parts:
            p_mount = p.mountpoint.lower() if os.name == 'nt' else p.mountpoint
            path_norm = path.lower() if os.name == 'nt' else path
            if path_norm.startswith(p_mount):
                partition = p
    except Exception:
        pass
        
    if not partition:
        console.print("[red]Could not map path to a known partition.[/red]")
        return
        
    db = Database()
    predictor = DiskPredictor(db)
    result = predictor.predict_full_date(partition)
    db.close()
    
    console.print(f"\n[bold white on blue] DISK FORECAST — {partition.mountpoint} [/bold white on blue]")
    gb_total = partition.total_bytes / (1024**3)
    gb_used = partition.used_bytes / (1024**3)
    
    console.print(f"Current:     {gb_used:.1f} GB / {gb_total:.1f} GB ({partition.usage_percent:.1f}%)")
    
    if result and result.days_until_full is not None:
        gb_growth = result.daily_growth_bytes / (1024**3)
        accel_str = "(accelerating ↑)" if result.is_accelerating else "(stable)"
        console.print(f"Growth Rate: {gb_growth:.2f} GB/day {accel_str}")
        console.print(f"\n⏰ ESTIMATED FULL: In [bold red]{result.days_until_full:.1f} days[/bold red]")
    else:
        console.print("Growth Rate: Static or Insufficient History.")
        console.print("\n⏰ ESTIMATED FULL: [bold green]Not growing[/bold green]")

@cli.command()
@click.option('--interval', default=300, help='Seconds between snapshots')
@click.argument('path', default='.')
def watch(interval, path):
    """Continuous monitoring mode. Snapshots disk state periodically."""
    import time
    from .platform import provider
    from .store.database import Database
    from .collectors.dir_tree import DirectoryTreeCollector

    path = os.path.abspath(path)
    db = Database()
    dir_collector = DirectoryTreeCollector()
    
    console.print(f"[bold blue]dxcli watch[/bold blue] started. Path: {path}, Interval: {interval}s")
    console.print("Press Ctrl+C to stop.")
    
    # Resolve which partition this path belongs to
    partition = None
    try:
        parts = provider.get_partitions()
        for p in parts:
            p_mount = p.mountpoint.lower() if os.name == 'nt' else p.mountpoint
            path_norm = path.lower() if os.name == 'nt' else path
            if path_norm.startswith(p_mount):
                partition = p
    except Exception:
        pass
    
    if not partition:
        console.print("[red]Could not map path to a known partition.[/red]")
        return

    try:
        while True:
            try:
                # Refresh partition usage
                try:
                    import psutil
                    usage = psutil.disk_usage(partition.mountpoint)
                    partition.used_bytes = usage.used
                    partition.free_bytes = usage.free
                    partition.total_bytes = usage.total
                except Exception:
                    pass

                # Scan the TARGET path, not the entire partition root
                top_dirs = dir_collector.scan(path)
                db.record_snapshot(partition, top_dirs)
                console.print(f"[{time.strftime('%H:%M:%S')}] Snapshot: {path} ({len(top_dirs)} dirs tracked)")
            except Exception as e:
                console.print(f"[yellow]Watch error: {e}[/yellow]")
            
            time.sleep(interval)
    except KeyboardInterrupt:
        db.close()
        console.print("\n[yellow]Watch stopped.[/yellow]")

@cli.command()
@click.option('--port', default=8000, help='Metrics server port')
@click.option('--bind', default='127.0.0.1', help='Address to bind to. Use 0.0.0.0 to expose to network.')
@click.option('--interval', default=300, help='Seconds between snapshots')
@click.argument('path', default='.')
def serve(port, bind, interval, path):
    """Run dxcli as a metrics-exporting daemon."""
    import threading
    from .outputs.metrics import start_metrics_server
    
    server_thread = threading.Thread(
        target=start_metrics_server, 
        args=(port, bind), 
        daemon=True
    )
    server_thread.start()
    
    display_addr = bind if bind != '0.0.0.0' else 'localhost'  # nosec B104
    console.print(f"[bold green]Sentinel Metrics Server[/bold green] live at http://{display_addr}:{port}/metrics")
    
    watch.callback(interval, path)

@cli.command()
def dash():
    """Launch the dxcli Textual Dashboard."""
    from .outputs.tui import DxApp
    app = DxApp()
    app.run()

if __name__ == '__main__':
    cli()
