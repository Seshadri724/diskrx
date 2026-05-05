import sys
import os

if sys.version_info < (3, 10):
    sys.exit("dxcli requires Python 3.10 or higher.")

if sys.platform == 'win32':
    os.environ.setdefault('PYTHONUTF8', '1')
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

import click
import time
from rich.console import Console

console = Console()

from .config import DEFAULT_CONFIG


@click.group(invoke_without_command=True)
@click.version_option(version="0.1.2", prog_name="dxcli")
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
@click.option('--json', 'as_json', is_flag=True, help='Output diagnosis in JSON format')
@click.option('--report', default=None, help='Generate an HTML report at the specified path.')
@click.option('--docker', is_flag=True, help='Analyze Docker disk usage and generate cleanup suggestions.')
@click.option('--ci', is_flag=True, help='Run in CI mode (exits with code 1 if disk is critical or policies violated).')
def diagnose(path, as_json, report, docker, ci):
    """Perform a deep scan & diagnostic of the path."""
    from .platform import provider
    from .collectors.dir_tree import DirectoryTreeCollector
    from .collectors.log_finder import LogFinderCollector
    from .collectors.stale_files import StaleFileCollector
    from .outputs.cli_report import render_diagnosis
    from .outputs.html_report import generate_html_report
    from .store.database import Database
    from .analyzers import PrescriptionEngine, RootCauseAnalyzer, CorrelationEngine, AnomalyDetector, DiskPredictor
    from .policy_engine import PolicyEngine

    path = os.path.abspath(path)
    if not as_json:
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

    # 10. Load and Run Plugins (Shopify style)
    from .analyzers.plugin_loader import PluginLoader
    manager = PluginLoader()
    plugins = manager.load_plugins()
    for plugin in plugins:
        try:
            plugin_prescriptions = plugin.analyze(top_dirs, logs, stales)
            prescriptions.extend(plugin_prescriptions)
        except Exception:
            continue

    # 10. Evaluate Policies
    policy_engine = PolicyEngine()
    violations = policy_engine.evaluate(top_dirs, logs, stales)
    for v in violations:
        # Turn violations into Sentinel alerts/anomalies for the UI to display them as critical
        anomalies.append(f"[{v.severity.upper()}] {v.rule_name}: {v.message} at {v.path}")

    app_accounting = []
    if not as_json and not ci:
        from .collectors.process_mapper import ProcessMapper
        app_accounting = ProcessMapper().get_application_accounting(path)

    if docker:
        from .collectors.docker import DockerCollector
        from .analyzers.docker_analyzer import DockerAnalyzer
        collector = DockerCollector()
        df_data = collector.get_system_df()
        if df_data:
            analyzer = DockerAnalyzer()
            docker_prescriptions = analyzer.analyze(df_data)
            prescriptions.extend(docker_prescriptions)

    if ci:
        has_critical = any("[CRITICAL]" in a for a in anomalies)
        disk_critical = partition and partition.usage_percent >= 90
        if has_critical or disk_critical:
            console.print("[bold red]CI Pipeline Failed: Disk usage critical or policy violation detected.[/bold red]")
            for a in anomalies:
                console.print(f"  {a}")
            sys.exit(1)

    db.close()

    if as_json:
        import json
        from dataclasses import asdict
        
        class DxEncoder(json.JSONEncoder):
            def default(self, obj):
                if hasattr(obj, "tolist"):
                    return obj.tolist()
                import numpy as np
                if isinstance(obj, (np.float64, np.float32)):
                    return float(obj)
                if isinstance(obj, (np.int64, np.int32)):
                    return int(obj)
                if isinstance(obj, np.bool_):
                    return bool(obj)
                return super().default(obj)

        output = {
            "path": path,
            "partition": asdict(partition) if partition else None,
            "top_dirs": [asdict(d) for d in top_dirs],
            "logs": [asdict(l) for l in logs],
            "stales": [asdict(s) for s in stales],
            "trends": correlated_trends,
            "prescriptions": [asdict(p) for p in prescriptions],
            "anomalies": anomalies,
            "prediction": asdict(prediction) if prediction else None
        }
        print(json.dumps(output, indent=2, cls=DxEncoder))
        return

    if report:
        from .outputs.html_report import generate_html_report
        generate_html_report(report, path, partition, top_dirs, logs, stales, 
                             correlated_trends, prescriptions, prediction)
        console.print(f"[bold green]Report generated:[/bold green] {os.path.abspath(report)}")

    # 10. Present the marketing screenshot
    render_diagnosis(path, partition, top_dirs, logs, stales,
                     trends=correlated_trends, prescriptions=prescriptions,
                     anomalies=anomalies, prediction=prediction, app_accounting=app_accounting)

@cli.command()
@click.argument('path', default='.')
@click.option('--hours', default=24, help='Hours back to compare against')
def diff(path, hours):
    """Show what changed since a past snapshot."""
    from .platform import provider
    from .store.database import Database
    from .collectors.dir_tree import DirectoryTreeCollector
    from rich.table import Table
    from rich.box import ROUNDED
    from .outputs.cli_report import format_bytes
    import time
    import os
    
    path = os.path.abspath(path)
    console.print(f"[dim]Calculating diff for {path} vs {hours} hours ago...[/dim]", end="\r")
    
    # 1. Get partition
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
    
    # 2. Get past snapshot
    target_ts = time.time() - (hours * 3600)
    past_snap = db.get_snapshot_closest_to(partition.mountpoint, target_ts)
    if not past_snap:
        console.print("[yellow]Not enough history to compute diff.[/yellow]")
        db.close()
        return
        
    past_metrics = past_snap["metrics"]
    actual_hours = (time.time() - past_snap["timestamp"]) / 3600
    
    # 3. Get current state (run a quick scan)
    dir_collector = DirectoryTreeCollector()
    top_dirs = dir_collector.scan(path)
    
    # 4. Calculate diffs
    diffs = []
    total_delta = 0
    for d in top_dirs:
        past_size = past_metrics.get(d.path, 0)
        delta = d.size_bytes - past_size
        total_delta += delta
        diffs.append({"path": d.path, "delta": delta, "current": d.size_bytes})
        
    db.close()
    
    diffs.sort(key=lambda x: abs(x["delta"]), reverse=True)
    
    # 5. Present diff
    console.print()
    table = Table(title=f"\n[bold white]DISK DIFF — Last {actual_hours:.1f} Hours[/bold white]", box=ROUNDED, expand=True)
    table.add_column("Path", style="cyan", no_wrap=True, ratio=4)
    table.add_column("Delta", justify="right", style="bold", ratio=1)
    table.add_column("Current Size", justify="right", style="dim", ratio=1)
    
    for d in diffs[:10]:
        delta_str = f"+{format_bytes(d['delta'])}" if d['delta'] >= 0 else format_bytes(d['delta'])
        color = "red" if d['delta'] > 0 else "green"
        
        display_path = d['path']
        if len(display_path) > 40:
            display_path = "..." + display_path[-37:]
            
        table.add_row(display_path, f"[{color}]{delta_str}[/{color}]", format_bytes(d['current']))
        
    total_color = "red" if total_delta > 0 else "green"
    total_str = f"+{format_bytes(total_delta)}" if total_delta >= 0 else format_bytes(total_delta)
    table.add_row("Total Delta", f"[{total_color}][bold]{total_str}[/bold][/{total_color}]", "")
    
    console.print(table)


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
@click.option('--alert-threshold', default=None, help='Alert if growth exceeds threshold (e.g., 100M, 1G)')
@click.option('--webhook', default=None, help='Webhook URL to notify on threshold breach')
@click.argument('path', default='.')
def watch(interval, alert_threshold, webhook, path):
    """Continuous monitoring mode. Snapshots disk state periodically."""
    import time
    from .platform import provider
    from .store.database import Database
    from .collectors.dir_tree import DirectoryTreeCollector
    from .outputs.cli_report import format_bytes

    def parse_bytes(s: str) -> int:
        if not s: return 0
        s = s.upper().strip()
        multipliers = {'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}
        for suffix, multiplier in multipliers.items():
            if s.endswith(suffix) or s.endswith(suffix + 'B'):
                num = s.rstrip('B').rstrip(suffix)
                return int(float(num) * multiplier)
        return int(s)

    threshold_bytes = parse_bytes(alert_threshold) if alert_threshold else 0

    path = os.path.abspath(path)
    db = Database()
    dir_collector = DirectoryTreeCollector()
    
    console.print(f"[bold blue]dxcli watch[/bold blue] started. Path: {path}, Interval: {interval}s")
    if threshold_bytes > 0:
        console.print(f"[bold red]Alert Threshold active:[/bold red] {format_bytes(threshold_bytes)}/interval")
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

    last_size = None

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
                
                # Check alert
                current_size = sum(d.size_bytes for d in top_dirs)
                alert_msg = ""
                if last_size is not None and threshold_bytes > 0:
                    delta = current_size - last_size
                    if delta > threshold_bytes:
                        alert_msg = f" [bold blink red]⚠ ALERT: Grew by {format_bytes(delta)}[/bold blink red]"
                        if webhook:
                            from .outputs.notifier import send_webhook
                            payload = {
                                "text": f"🚨 dxcli Alert: Path '{path}' grew by {format_bytes(delta)} in {interval}s.",
                                "path": path,
                                "delta_bytes": delta
                            }
                            send_webhook(webhook, payload)
                last_size = current_size

                console.print(f"[{time.strftime('%H:%M:%S')}] Snapshot: {path} ({len(top_dirs)} dirs tracked){alert_msg}")
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
@click.argument('path', default='.')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompts')
def heal(path, yes):
    """Automatically fix issues identified during diagnosis."""
    from .platform import provider
    from .collectors.log_finder import LogFinderCollector
    from .collectors.stale_files import StaleFileCollector
    from .analyzers import PrescriptionEngine
    from .heal_engine import HealEngine
    
    path = os.path.abspath(path)
    console.print(f"[bold cyan]Heal Engine[/bold cyan] scanning {path}...")
    
    # 1. Run collectors
    log_collector = LogFinderCollector()
    logs = log_collector.scan([path])
    
    stale_collector = StaleFileCollector()
    stales = stale_collector.scan([path])
    
    # 2. Get prescriptions
    engine = PrescriptionEngine()
    prescriptions = engine.synthesize(logs, stales)
    
    if not prescriptions:
        console.print("[green]No issues found that require healing.[/green]")
        return
        
    # 3. Present and Execute
    healer = HealEngine()
    count = 0
    for p in prescriptions:
        if not p.target_path:
            continue
            
        if not yes:
            if not click.confirm(f"Execute action: {p.name}?"):
                continue
        
        console.print(f"Applying: [dim]{p.name}[/dim]...", end="")
        if healer.execute(p):
            console.print(" [bold green]DONE[/bold green]")
            count += 1
        else:
            console.print(" [bold red]FAILED[/bold red]")
            
    console.print(f"\n[bold green]Healing session complete. {count} actions applied.[/bold green]")
    console.print(healer.generate_sleep_insurance_report())
    console.print(f"Audit log: {healer.audit_log_path}")

@cli.command()
def undo():
    """Revert the last healing action."""
    from .heal_engine import HealEngine
    healer = HealEngine()
    
    result = healer.undo()
    if result:
        console.print(f"[bold green]Undo successful:[/bold green] {result}")
    else:
        console.print("[yellow]No actions to undo.[/yellow]")

@cli.command()
def dash():
    """Launch the dxcli Textual Dashboard."""
    from .outputs.tui import DxApp
    app = DxApp()
    app.run()

@cli.command()
@click.pass_context
def demo(ctx):
    """Run a high-impact demo with synthetic data."""
    from .demo_seeder import DemoSeeder
    from .store.database import Database
    
    console.print("[bold blue]🚀 Starting dxcli Hero Demo...[/bold blue]")
    db = Database()
    seeder = DemoSeeder(db)
    
    console.print("  [dim]Cleaning up old demo data...[/dim]")
    sandbox_path = seeder.setup_sandbox()
    
    console.print("  [dim]Seeding 7 days of synthetic growth history...[/dim]")
    seeder.seed_history()
    db.close()
    
    console.print("  [bold green]Success![/bold green] Running diagnosis on demo sandbox...\n")
    time.sleep(1)
    
    # Invoke diagnose on the sandbox
    ctx.invoke(diagnose, path=sandbox_path)

if __name__ == '__main__':
    cli()
