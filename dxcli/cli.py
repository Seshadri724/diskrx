import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict

import click
from rich.box import ROUNDED
from rich.console import Console
from rich.table import Table

from .config import get_config
from .runtime import DxCliError, ExitCode, validate_bind_address, validate_webhook_url
from . import __version__

if sys.version_info < (3, 8):
    sys.exit("dxcli requires Python 3.8 or higher.")

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

console = Console()
logger = logging.getLogger(__name__)


def fail(message: str, code: ExitCode) -> None:
    raise DxCliError(message, code)


def apply_niceness(nice: int = None, ionice: bool = False) -> None:
    if sys.platform != "win32":
        if nice is not None:
            try:
                os.nice(nice)
            except OSError as e:
                logger.warning("Could not set nice priority: %s", e)
        if ionice:
            try:
                subprocess.run(
                    ["ionice", "-c3", "-p", str(os.getpid())],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False
                )
            except Exception as e:
                logger.warning("Could not set ionice: %s", e)


def resolve_target_config(path: str, target: str = None):
    if not target:
        return os.path.abspath(path), None, None
    config = get_config()
    if target not in config.targets:
        fail(f"Target '{target}' not found in config.", ExitCode.VALIDATION_ERROR)
    target_cfg = config.targets[target]
    return os.path.abspath(target_cfg.path), target_cfg.alert_threshold, target_cfg.interval


def parse_bytes(raw: str) -> int:
    if not raw:
        return 0
    value = raw.upper().strip()
    multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    for suffix, multiplier in multipliers.items():
        if value.endswith(suffix) or value.endswith(f"{suffix}B"):
            number = value.rstrip("B").rstrip(suffix)
            return int(float(number) * multiplier)
    return int(value)


def get_database():
    from .store.database import Database

    try:
        return Database()
    except Exception as exc:
        fail(f"Could not open database: {exc}", ExitCode.RUNTIME_ERROR)


def get_partition_for_path(path: str):
    from .platform import provider

    partition = provider.get_partition_for_path(path)
    if not partition:
        fail("Could not map path to a known partition.", ExitCode.VALIDATION_ERROR)
    return partition


def run_watch_loop(path, interval, threshold_bytes, webhook, notify_desktop, iteration_limit=None, scan_threads=None, nice=None, ionice=False):
    from .collectors.dir_tree import DirectoryTreeCollector

    apply_niceness(nice, ionice)
    webhook = validate_webhook_url(webhook)
    if interval <= 0:
        fail("Interval must be greater than 0 seconds.", ExitCode.VALIDATION_ERROR)

    path = os.path.abspath(path)
    partition = get_partition_for_path(path)
    db = get_database()
    dir_collector = DirectoryTreeCollector(max_threads=scan_threads)


    console.print(f"[bold blue]dxcli watch[/bold blue] started. Path: {path}, Interval: {interval}s")
    if threshold_bytes > 0:
        from .outputs.cli_report import format_bytes

        console.print(f"[bold red]Alert Threshold active:[/bold red] {format_bytes(threshold_bytes)}/interval")
    console.print("Press Ctrl+C to stop.")

    last_size = None
    iterations = 0
    try:
        while iteration_limit is None or iterations < iteration_limit:
            iterations += 1
            try:
                try:
                    import psutil

                    usage = psutil.disk_usage(partition.mountpoint)
                    partition.used_bytes = usage.used
                    partition.free_bytes = usage.free
                    partition.total_bytes = usage.total
                except Exception as exc:
                    logger.warning("Partition refresh failed for %s: %s", partition.mountpoint, exc)

                top_dirs = dir_collector.scan(path)
                try:
                    db.record_snapshot(partition, top_dirs)
                except Exception as exc:
                    console.print(f"[yellow]Warning: Could not record snapshot: {exc}[/yellow]")

                current_size = sum(d.size_bytes for d in top_dirs)
                alert_msg = ""
                if last_size is not None and threshold_bytes > 0:
                    from .outputs.cli_report import format_bytes

                    delta = current_size - last_size
                    if delta > threshold_bytes:
                        alert_msg = f" [bold red]ALERT: Grew by {format_bytes(delta)}[/bold red]"
                        if webhook:
                            from .outputs.notifier import send_webhook

                            payload = {
                                "text": f"dxcli alert: Path '{path}' grew by {format_bytes(delta)} in {interval}s.",
                                "path": path,
                                "delta_bytes": delta,
                            }
                            success, error = send_webhook(webhook, payload)
                            if not success:
                                console.print(f"[yellow]Webhook failed: {error}[/yellow]")
                        if notify_desktop:
                            from .outputs.notifier import send_desktop_notification

                            send_desktop_notification(
                                "dxcli Disk Alert",
                                f"Path '{path}' grew by {format_bytes(delta)}.",
                            )
                last_size = current_size
                console.print(
                    f"[{time.strftime('%H:%M:%S')}] Snapshot: {path} ({len(top_dirs)} dirs tracked){alert_msg}"
                )
            except Exception as exc:
                console.print(f"[yellow]Watch iteration failed: {type(exc).__name__}: {exc}[/yellow]")

            if iteration_limit is not None and iterations >= iteration_limit:
                break
            time.sleep(interval)
    except KeyboardInterrupt as exc:
        raise click.exceptions.Exit(int(ExitCode.INTERRUPTED)) from exc
    finally:
        db.close()


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="dxcli")
@click.pass_context
def cli(ctx):
    """dxcli - disk diagnostics for operators."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(diagnose, path=".")


@cli.command()
def status():
    """Show basic disk status for all partitions."""
    from .platform import provider

    console.print("[bold blue]Disk Status[/bold blue]")
    try:
        partitions = provider.get_partitions()
    except Exception as exc:
        fail(f"Error fetching partitions: {exc}", ExitCode.RUNTIME_ERROR)

    for part in partitions:
        width = 20
        filled = int((part.usage_percent / 100) * width)
        bar = ("#" * filled) + ("-" * (width - filled))
        gb_total = part.total_bytes / (1024**3)
        gb_used = part.used_bytes / (1024**3)
        console.print(
            f"  {part.mountpoint:<12} {bar} {part.usage_percent:5.1f}%  used {gb_used:.1f}GB / {gb_total:.1f}GB"
        )


@cli.command()
@click.argument("path", default=".")
@click.option("--json", "as_json", is_flag=True, help="Output diagnosis in JSON format")
@click.option("--report", default=None, help="Generate an HTML report at the specified path.")
@click.option("--docker", is_flag=True, help="Analyze Docker disk usage and generate cleanup suggestions.")
@click.option("--ci", is_flag=True, help="Run in CI mode and fail on critical disk or policy issues.")
@click.option("--classify", is_flag=True, help="Group disk usage by semantic category.")
@click.option("--target", help="Use a named target defined in config.yaml")
@click.option("--enable-plugins", is_flag=True, help="Opt-in to execute local plugins from ~/.dx/plugins.")
@click.option("--scan-threads", type=int, default=None, help="Max threads to use for scanning directories.")
@click.option("--nice", type=int, default=None, help="Set nice priority level (Linux only).")
@click.option("--ionice", is_flag=True, help="Set ionice idle priority (Linux only).")
def diagnose(path, as_json, report, docker, ci, classify, target, enable_plugins, scan_threads, nice, ionice):
    """Perform a deep scan and diagnostic of the path."""
    from .analyzers import (
        StatisticalAnomalyDetector,
        CorrelationEngine,
        DiskPredictor,
        PrescriptionEngine,
        RootCauseAnalyzer,
    )
    from .collectors.log_finder import LogFinderCollector
    from .collectors.process_mapper import ProcessMapper
    from .collectors.stale_files import StaleFileCollector
    from .collectors.dir_tree import DirectoryTreeCollector
    from .outputs.cli_report import render_diagnosis
    from .outputs.html_report import generate_html_report
    from .policy_engine import PolicyEngine
    from .platform import provider

    path, _, _ = resolve_target_config(path, target)
    if not as_json:
        console.print(f"[dim]Scanning {path}...[/dim]", end="\r")

    apply_niceness(nice, ionice)
    partition = provider.get_partition_for_path(path)
    dir_collector = DirectoryTreeCollector(max_threads=scan_threads)
    top_dirs = dir_collector.scan(path)
    logs = LogFinderCollector().scan([path])
    stales = StaleFileCollector().scan([path])

    db = get_database()
    try:
        if partition:
            try:
                db.record_snapshot(partition, top_dirs)
            except Exception as exc:
                console.print(f"[yellow]Warning: Could not record snapshot: {exc}[/yellow]")

        trends = RootCauseAnalyzer(db).attribute_cause(top_dirs)
        correlated_trends = CorrelationEngine(db=db).correlate(trends)
        for trend in correlated_trends:
            history = db.get_dir_history(trend["path"], limit=10)
            trend["history"] = [entry["size_bytes"] for entry in history]

        anomalies = []
        detector = StatisticalAnomalyDetector(db)
        for node in top_dirs[:5]:
            result = detector.check_for_anomalies(node.path)
            if result:
                anomalies.append(result)

        prediction = DiskPredictor(db).predict_full_date(partition) if partition else None
        prescriptions = PrescriptionEngine().synthesize(logs, stales, path)


        if enable_plugins:
            from .analyzers.plugin_loader import PluginLoader

            for plugin in PluginLoader().load_plugins():
                try:
                    prescriptions.extend(plugin.analyze(top_dirs, logs, stales))
                except Exception as exc:
                    console.print(f"[yellow]Warning: Plugin execution failed - {exc}[/yellow]")

        violations = PolicyEngine().evaluate(top_dirs, logs, stales)
        for violation in violations:
            anomalies.append(
                f"[{violation.severity.upper()}] {violation.rule_name}: {violation.message} at {violation.path}"
            )

        app_accounting = []
        active_writers = []
        if not as_json and not ci:
            mapper = ProcessMapper()
            app_accounting = mapper.get_application_accounting(path)
            active_writers = mapper.get_active_writers(path, interval=0.5)

        if docker:
            from .analyzers.docker_analyzer import DockerAnalyzer
            from .collectors.docker import DockerCollector

            docker_data = DockerCollector().get_system_df()
            if docker_data:
                prescriptions.extend(DockerAnalyzer().analyze(docker_data))

        classification = None
        if classify:
            from .analyzers.classification import ClassificationEngine

            classification = ClassificationEngine().get_summary(top_dirs)

        if ci:
            has_critical = any("[CRITICAL]" in alert for alert in anomalies)
            disk_critical = bool(partition and partition.usage_percent >= 90)
            if has_critical or disk_critical:
                console.print("[bold red]CI pipeline failed: disk usage critical or policy violation detected.[/bold red]")
                for alert in anomalies:
                    console.print(f"  {alert}")
                raise click.exceptions.Exit(int(ExitCode.CI_FAILURE))
    finally:
        db.close()

    if as_json:
        class DxEncoder(json.JSONEncoder):
            def default(self, obj):
                from dataclasses import is_dataclass, asdict
                if is_dataclass(obj):
                    return asdict(obj)
                if hasattr(obj, "tolist"):
                    return obj.tolist()
                try:
                    import numpy as np

                    if isinstance(obj, (np.float64, np.float32)):
                        return float(obj)
                    if isinstance(obj, (np.int64, np.int32)):
                        return int(obj)
                    if isinstance(obj, np.bool_):
                        return bool(obj)
                except Exception:
                    pass
                return super().default(obj)

        output = {
            "path": path,
            "partition": asdict(partition) if partition else None,
            "top_dirs": [asdict(item) for item in top_dirs],
            "logs": [asdict(item) for item in logs],
            "stales": [asdict(item) for item in stales],
            "trends": correlated_trends,
            "prescriptions": [asdict(item) for item in prescriptions],
            "anomalies": anomalies,
            "prediction": asdict(prediction) if prediction else None,
            "classification": classification,
        }
        print(json.dumps(output, indent=2, cls=DxEncoder))
        return

    if report:
        generate_html_report(
            report,
            path,
            partition,
            top_dirs,
            logs,
            stales,
            correlated_trends,
            prescriptions,
            prediction,
        )
        console.print(f"[bold green]Report generated:[/bold green] {os.path.abspath(report)}")

    render_diagnosis(
        path,
        partition,
        top_dirs,
        logs,
        stales,
        trends=correlated_trends,
        prescriptions=prescriptions,
        anomalies=anomalies,
        prediction=prediction,
        app_accounting=app_accounting,
        classification=classification,
        active_writers=active_writers,
    )


@cli.command()
@click.argument("path", default=".")
@click.option("--hours", default=24, help="Hours back to compare against")
def diff(path, hours):
    """Show what changed since a past snapshot."""
    from .collectors.dir_tree import DirectoryTreeCollector
    from .outputs.cli_report import format_bytes

    path = os.path.abspath(path)
    console.print(f"[dim]Calculating diff for {path} vs {hours} hours ago...[/dim]", end="\r")
    partition = get_partition_for_path(path)
    db = get_database()
    try:
        target_ts = time.time() - (hours * 3600)
        past_snapshot = db.get_snapshot_closest_to(partition.mountpoint, target_ts)
        if not past_snapshot:
            console.print("[yellow]Not enough history to compute diff.[/yellow]")
            return
        actual_hours = (time.time() - past_snapshot["timestamp"]) / 3600
        top_dirs = DirectoryTreeCollector().scan(path)
        diffs = []
        total_delta = 0
        for node in top_dirs:
            past_size = past_snapshot["metrics"].get(node.path, 0)
            delta = node.size_bytes - past_size
            total_delta += delta
            diffs.append({"path": node.path, "delta": delta, "current": node.size_bytes})
    finally:
        db.close()

    diffs.sort(key=lambda item: abs(item["delta"]), reverse=True)
    table = Table(title=f"\n[bold white]DISK DIFF - Last {actual_hours:.1f} Hours[/bold white]", box=ROUNDED, expand=True)
    table.add_column("Path", style="cyan", no_wrap=True, ratio=4)
    table.add_column("Delta", justify="right", style="bold", ratio=1)
    table.add_column("Current Size", justify="right", style="dim", ratio=1)

    for item in diffs[:10]:
        delta_str = f"+{format_bytes(item['delta'])}" if item["delta"] >= 0 else format_bytes(item["delta"])
        color = "red" if item["delta"] > 0 else "green"
        display_path = item["path"] if len(item["path"]) <= 40 else "..." + item["path"][-37:]
        table.add_row(display_path, f"[{color}]{delta_str}[/{color}]", format_bytes(item["current"]))

    total_color = "red" if total_delta > 0 else "green"
    total_str = f"+{format_bytes(total_delta)}" if total_delta >= 0 else format_bytes(total_delta)
    table.add_row("Total Delta", f"[{total_color}][bold]{total_str}[/bold][/{total_color}]", "")
    console.print()
    console.print(table)


@cli.command()
@click.argument("path", default=".")
def predict(path):
    """Predict when a disk will become full based on history."""
    from .analyzers import DiskPredictor

    path = os.path.abspath(path)
    partition = get_partition_for_path(path)
    db = get_database()
    try:
        result = DiskPredictor(db).predict_full_date(partition)
    finally:
        db.close()

    console.print(f"\n[bold white on blue] DISK FORECAST - {partition.mountpoint} [/bold white on blue]")
    gb_total = partition.total_bytes / (1024**3)
    gb_used = partition.used_bytes / (1024**3)
    console.print(f"Current:     {gb_used:.1f} GB / {gb_total:.1f} GB ({partition.usage_percent:.1f}%)")
    if result and result.days_until_full is not None:
        gb_growth = result.daily_growth_bytes / (1024**3)
        accel_str = "(accelerating)" if result.is_accelerating else "(stable)"
        console.print(f"Growth Rate: {gb_growth:.2f} GB/day {accel_str}")
        console.print(f"\nEstimated Full: In [bold red]{result.days_until_full:.1f} days[/bold red]")
    else:
        console.print("Growth Rate: Static or insufficient history.")
        console.print("\nEstimated Full: [bold green]Not growing[/bold green]")


@cli.command()
@click.option("--interval", default=300, help="Seconds between snapshots")
@click.option("--alert-threshold", default=None, help="Alert if growth exceeds threshold (e.g. 100M, 1G)")
@click.option("--webhook", default=None, help="Webhook URL to notify on threshold breach")
@click.option("--notify-desktop", is_flag=True, help="Send a desktop notification on threshold breach")
@click.option("--target", help="Use a named target defined in config.yaml")
@click.option("--scan-threads", type=int, default=None, help="Max threads to use for scanning directories.")
@click.option("--nice", type=int, default=None, help="Set nice priority level (Linux only).")
@click.option("--ionice", is_flag=True, help="Set ionice idle priority (Linux only).")
@click.argument("path", default=".")
def watch(interval, alert_threshold, webhook, notify_desktop, target, scan_threads, nice, ionice, path):
    """Continuous monitoring mode. Snapshots disk state periodically."""
    path, target_threshold, target_interval = resolve_target_config(path, target)
    if target_threshold:
        alert_threshold = target_threshold
    if target_interval:
        interval = target_interval
    threshold_bytes = parse_bytes(alert_threshold) if alert_threshold else 0
    run_watch_loop(path, interval, threshold_bytes, webhook, notify_desktop, scan_threads=scan_threads, nice=nice, ionice=ionice)


@cli.command()
@click.option("--port", default=8000, help="Metrics server port")
@click.option("--bind", default="127.0.0.1", help="Address to bind to. Use 0.0.0.0 to expose to network.")
@click.option("--interval", default=300, help="Seconds between snapshots")
@click.option("--auth-token", default=None, help="Bearer token for metrics authentication.")
@click.argument("path", default=".")
def serve(port, bind, interval, auth_token, path):
    """Run dxcli as a metrics-exporting daemon."""
    from .outputs.metrics import create_metrics_server

    bind = validate_bind_address(bind)
    if interval <= 0:
        fail("Interval must be greater than 0 seconds.", ExitCode.VALIDATION_ERROR)
    
    if bind == "0.0.0.0" and not auth_token:
        fail("Binding to 0.0.0.0 is refused without --auth-token.", ExitCode.UNSAFE_OPERATION)

    if bind == "0.0.0.0":
        console.print("[bold yellow]WARNING: Binding to 0.0.0.0 exposes metrics to the network.[/bold yellow]")
    try:
        server = create_metrics_server(port, bind, auth_token)
    except OSError as exc:
        fail(f"Could not start metrics server on {bind}:{port}: {exc}", ExitCode.RUNTIME_ERROR)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    display_addr = bind if bind != "0.0.0.0" else "localhost"
    console.print(f"[bold green]Sentinel Metrics Server[/bold green] live at http://{display_addr}:{port}/metrics")
    try:
        run_watch_loop(path, interval, 0, None, False)
    finally:
        server.shutdown()
        server.server_close()


@cli.command()
@click.argument("path", default=".")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
@click.option("--dry-run", is_flag=True, help="Simulate healing actions without executing them")
def heal(path, yes, dry_run):
    """Apply safe, scoped healing actions for the given path."""
    from .analyzers import PrescriptionEngine
    from .collectors.log_finder import LogFinderCollector
    from .collectors.stale_files import StaleFileCollector
    from .heal_engine import HealEngine
    from .outputs.cli_report import format_bytes

    path = os.path.abspath(path)
    console.print(f"[bold cyan]Heal Engine[/bold cyan] scanning {path}...")
    logs = LogFinderCollector().scan([path])
    stales = StaleFileCollector().scan([path])
    prescriptions = PrescriptionEngine().synthesize(logs, stales, path)
    actionable = [item for item in prescriptions if item.action_type in ("delete", "create_file") and item.target_path]
    manual = [item for item in prescriptions if item.action_type in ("manual", "info")]

    if not actionable and not manual:
        console.print("[green]No healing actions available.[/green]")
        return

    if manual:
        console.print("\n[bold blue]Manual Actions (run these yourself):[/bold blue]")
        for item in manual:
            console.print(f"  [dim]•[/dim] {item.name}")
            console.print(f"    [dim]Command:[/dim] {item.template}")
        console.print()

    if not actionable:
        console.print("[green]No automated healing actions available.[/green]")
        return

    healer = HealEngine(allowed_scope=path)

    if dry_run:
        console.print("\n[bold yellow]DRY RUN SIMULATION:[/bold yellow]")
        for prescription in actionable:
            success = healer.execute(prescription, dry_run=True)
            if success:
                console.print(f"  [yellow]Prescription:[/yellow] {prescription.name}")
                console.print(f"  [yellow]Target Path :[/yellow] {prescription.target_path}")
                console.print(f"  [yellow]Savings     :[/yellow] {format_bytes(prescription.size_savings_bytes)}")
                console.print()
            else:
                console.print(f"  [red]Prescription rejected by safety policies:[/red] {prescription.name}\n")
        console.print("[bold green]Dry run completed. No files were modified.[/bold green]")
        return

    count = 0
    for prescription in actionable:
        if not yes and not click.confirm(f"Execute action: {prescription.name}?"):
            continue
        console.print(f"Applying: [dim]{prescription.name}[/dim]...", end="")
        if healer.execute(prescription):
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

    result = HealEngine().undo()
    if not result:
        fail("Nothing to undo or undo failed.", ExitCode.RUNTIME_ERROR)
    console.print(f"[bold green]Reverted:[/bold green] {result}")


@cli.command()
def dash():
    """Launch the dxcli textual dashboard."""
    from .outputs.tui import DxApp

    DxApp().run()


@cli.command()
@click.pass_context
def demo(ctx):
    """Run the synthetic demo dataset."""
    from .demo_seeder import DemoSeeder

    console.print("[bold blue]Starting dxcli demo...[/bold blue]")
    db = get_database()
    try:
        seeder = DemoSeeder(db)
        console.print("  [dim]Cleaning up old demo data...[/dim]")
        sandbox_path = seeder.setup_sandbox()
        console.print("  [dim]Seeding synthetic growth history...[/dim]")
        seeder.seed_history()
    finally:
        db.close()

    console.print("  [bold green]Success![/bold green] Running diagnosis on demo sandbox...\n")
    time.sleep(1)
    ctx.invoke(diagnose, path=sandbox_path)


@cli.command()
@click.argument("action", type=click.Choice(["start", "stop", "status"]))
@click.option("--command", default="watch", type=click.Choice(["watch", "serve"]), help="Command to run in background")
@click.option("--target", help="Named target to monitor")
@click.option("--notify-desktop", is_flag=True, help="Enable desktop notifications")
@click.option("--webhook", help="Webhook URL to notify")
def daemon(action, command, target, notify_desktop, webhook):
    """Manage dxcli as a background daemon."""
    from .state import atomic_write, get_state_dir

    pid_file = os.path.join(get_state_dir(), f"daemon_{command}.pid")

    if action == "start":
        if os.path.exists(pid_file):
            fail(f"Daemon for {command} is already running or PID file exists.", ExitCode.UNSAFE_OPERATION)

        cmd = [sys.executable, "-m", "dxcli.cli", command]
        if target:
            cmd.extend(["--target", target])
        if notify_desktop:
            cmd.append("--notify-desktop")
        if webhook:
            validate_webhook_url(webhook)
            cmd.extend(["--webhook", webhook])

        if sys.platform == "win32":
            process = subprocess.Popen(cmd, creationflags=0x00000008, close_fds=True)
        else:
            process = subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.2)
        if process.poll() is not None:
            fail(f"Daemon process exited during startup with code {process.returncode}.", ExitCode.RUNTIME_ERROR)
        atomic_write(pid_file, str(process.pid))
        console.print(f"[bold green]Started {command} daemon with PID {process.pid}[/bold green]")
        return

    if action == "stop":
        if not os.path.exists(pid_file):
            fail(f"No daemon running for {command}.", ExitCode.RUNTIME_ERROR)
        try:
            with open(pid_file, "r", encoding="utf-8") as handle:
                pid = int(handle.read().strip())
        except Exception as exc:
            fail(f"Failed to read PID file. It may be corrupted: {exc}", ExitCode.RUNTIME_ERROR)
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
            else:
                os.kill(pid, signal.SIGTERM)
            console.print(f"[bold green]Stopped {command} daemon (PID {pid}).[/bold green]")
        except Exception as exc:
            fail(f"Failed to stop daemon: {exc}", ExitCode.RUNTIME_ERROR)
        finally:
            if os.path.exists(pid_file):
                try:
                    os.remove(pid_file)
                except OSError:
                    pass
        return

    try:
        import psutil
    except Exception as exc:
        fail(f"psutil is required for daemon status checks: {exc}", ExitCode.RUNTIME_ERROR)

    if not os.path.exists(pid_file):
        fail(f"Daemon {command} is not running.", ExitCode.RUNTIME_ERROR)
    try:
        with open(pid_file, "r", encoding="utf-8") as handle:
            pid = int(handle.read().strip())
        if psutil.pid_exists(pid):
            console.print(f"[bold green]Daemon {command} is RUNNING (PID {pid})[/bold green]")
            return
        console.print(f"[yellow]Daemon {command} is NOT running (stale PID {pid}).[/yellow]")
        try:
            os.remove(pid_file)
        except OSError:
            pass
        fail(f"Daemon {command} is not running.", ExitCode.RUNTIME_ERROR)
    except ValueError:
        fail("Daemon PID file is corrupted.", ExitCode.RUNTIME_ERROR)


@cli.command()
@click.argument("path", default=".")
@click.option("--json", "as_json", is_flag=True, help="Emit fleet-ready host telemetry as JSON.")
@click.option("--max-items", default=100, show_default=True, help="Maximum top dirs, logs, and stale files in output.")
def snapshot(path, as_json, max_items):
    """Collect a fleet-ready local host telemetry snapshot."""
    from .enterprise import AgentSnapshotCollector
    from .outputs.cli_report import format_bytes

    if max_items < 1:
        fail("--max-items must be greater than 0.", ExitCode.VALIDATION_ERROR)
    snapshot_data = AgentSnapshotCollector().collect(path)
    snapshot_data.top_dirs = snapshot_data.top_dirs[:max_items]
    snapshot_data.logs = snapshot_data.logs[:max_items]
    snapshot_data.stales = snapshot_data.stales[:max_items]
    snapshot_data.risk_signals = snapshot_data.risk_signals[:max_items]
    if as_json:
        print(json.dumps(asdict(snapshot_data), indent=2))
        return

    console.print("[bold blue]Host Storage Snapshot[/bold blue]")
    console.print(f"Host: {snapshot_data.hostname}")
    console.print(f"Risk: [bold]{snapshot_data.risk_level}[/bold] ({snapshot_data.risk_score})")
    console.print(f"Path: {snapshot_data.scan_path}")

    table = Table(title="Partitions", box=ROUNDED)
    table.add_column("Mount")
    table.add_column("Usage", justify="right")
    table.add_column("Used", justify="right")
    table.add_column("Total", justify="right")
    for partition in snapshot_data.partitions:
        table.add_row(
            partition.mountpoint,
            f"{partition.usage_percent:.1f}%",
            format_bytes(partition.used_bytes),
            format_bytes(partition.total_bytes),
        )
    console.print(table)

    if snapshot_data.risk_signals:
        signal_table = Table(title="Risk Signals", box=ROUNDED)
        signal_table.add_column("Severity")
        signal_table.add_column("Category")
        signal_table.add_column("Score", justify="right")
        signal_table.add_column("Message")
        for signal in snapshot_data.risk_signals[:10]:
            signal_table.add_row(signal.severity, signal.category, str(signal.score), signal.message)
        console.print(signal_table)


@cli.command()
@click.argument("hosts", nargs=-1)
@click.option("--port", default=8000, help="Port of dxcli serve instances")
def fleet(hosts, port):
    """Aggregate metrics from multiple dxcli serve instances."""
    import urllib.error
    import urllib.request

    if not hosts:
        fail("Usage: dxcli fleet host1 host2 ...", ExitCode.VALIDATION_ERROR)

    table = Table(title="[bold white]dxcli Fleet Dashboard[/bold white]", box=ROUNDED)
    table.add_column("Host", style="cyan")
    table.add_column("Partition", style="white")
    table.add_column("Usage", justify="right")
    table.add_column("Status", justify="center")

    for host in hosts:
        url = f"http://{host}:{port}/metrics"
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                content = response.read().decode("utf-8")
            metrics = {}
            for line in content.splitlines():
                if line.startswith("dx_partition_usage_percent"):
                    parts = line.split()
                    metrics[parts[0].split('"')[1]] = parts[1]
            for mount, usage in metrics.items():
                color = "red" if float(usage) > 90 else "yellow" if float(usage) > 75 else "green"
                table.add_row(host, mount, f"[{color}]{usage}%[/{color}]", "[bold green]ONLINE[/bold green]")
        except urllib.error.URLError as exc:
            table.add_row(host, "---", "---", f"[bold red]OFFLINE[/bold red] ({exc.reason})")
        except Exception as exc:
            table.add_row(host, "---", "---", f"[bold red]ERROR[/bold red] ({type(exc).__name__})")

    console.print(table)


@cli.command()
def add_target():
    """Interactively add a named target to the configuration."""
    from .config import TargetConfig

    name = click.prompt("Name for this target")
    path = click.prompt("Path to monitor", default=os.getcwd())
    threshold = click.prompt("Alert threshold (e.g. 10GB)", default="", show_default=False)
    interval = click.prompt("Check interval in seconds", type=int, default=300)
    config = get_config()
    config.targets[name] = TargetConfig(
        path=os.path.abspath(path),
        alert_threshold=threshold if threshold else None,
        interval=interval,
    )
    config.save()
    console.print(f"[bold green]Target '{name}' saved to config.yaml[/bold green]")


@cli.command()
@click.option("--target", help="Target name to generate service for")
@click.option("--user", default="dxcli-agent", help="Service user name")
def generate_service(target, user):
    """Generate a systemd service file for a target."""
    from .state import atomic_write

    if sys.platform != "linux":
        fail("Service generation is currently only optimized for Linux (systemd).", ExitCode.RUNTIME_ERROR)
    config = get_config()
    if not target or target not in config.targets:
        fail("Please specify a valid --target defined in config.yaml", ExitCode.VALIDATION_ERROR)

    service_content = f"""[Unit]
Description=dxcli watch for {target}
After=network.target

[Service]
User={user}
Group={user}
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadOnlyPaths=/
ReadWritePaths={os.path.expanduser("~")}/.dx
PrivateTmp=true
ExecStart={sys.executable} -m dxcli.cli watch --target {target}
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""
    file_path = f"dxcli-{target}.service"
    try:
        atomic_write(file_path, service_content, mode=0o644)
    except Exception as exc:
        fail(f"Failed to generate service file: {exc}", ExitCode.RUNTIME_ERROR)
    console.print(f"[bold green]Service file generated:[/bold green] {file_path}")
    console.print(
        f"[dim]To install:[/dim]\n  sudo cp {file_path} /etc/systemd/system/\n"
        f"  sudo systemctl daemon-reload\n  sudo systemctl enable dxcli-{target} --now"
    )


@cli.command()
@click.option("--days", default=90, help="Days back of snapshots to retain.")
def prune(days):
    """Prune historical database snapshots older than the specified days."""
    db = get_database()
    try:
        console.print(f"Pruning snapshots older than {days} days...")
        db.prune_old(days)
        console.print("[bold green]Pruning complete.[/bold green]")
    finally:
        db.close()


@cli.group()
def plugins():
    """Manage dxcli plugins."""
    pass


@plugins.command("trust")
@click.argument("path", type=click.Path(exists=True, file_okay=True, dir_okay=False))
def trust(path):
    """Trust a plugin by adding its SHA256 and filename to the allowlist."""
    from .analyzers.plugin_loader import compute_sha256
    from .state import get_state_dir
    
    abs_path = os.path.abspath(path)
    filename = os.path.basename(abs_path)
    file_sha = compute_sha256(abs_path)
    
    if not file_sha:
        fail(f"Could not compute SHA256 for {path}", ExitCode.RUNTIME_ERROR)
        
    console.print(f"Plugin:  {filename}")
    console.print(f"SHA256:  {file_sha}")
    
    if click.confirm("Do you want to trust this plugin?"):
        allowlist_path = os.path.join(get_state_dir(), "plugins.allowlist")
        exists = False
        if os.path.exists(allowlist_path):
            with open(allowlist_path, "r", encoding="utf-8") as f:
                for line in f:
                    if file_sha in line:
                        exists = True
                        break
        
        if exists:
            console.print("[yellow]Plugin is already trusted.[/yellow]")
            return
            
        try:
            with open(allowlist_path, "a", encoding="utf-8") as f:
                f.write(f"{file_sha}  {filename}\n")
            console.print("[bold green]Plugin successfully added to allowlist.[/bold green]")
        except OSError as e:
            fail(f"Failed to write to allowlist: {e}", ExitCode.RUNTIME_ERROR)


if __name__ == "__main__":
    cli()

