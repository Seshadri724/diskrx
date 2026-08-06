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
                    check=False,
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
    return (
        os.path.abspath(target_cfg.path),
        target_cfg.alert_threshold,
        target_cfg.interval,
    )


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


def run_watch_loop(
    path,
    interval,
    threshold_bytes,
    webhook,
    notify_desktop,
    iteration_limit=None,
    scan_threads=None,
    nice=None,
    ionice=False,
):
    from .engine import run_diagnosis

    apply_niceness(nice, ionice)
    webhook = validate_webhook_url(webhook)
    if interval <= 0:
        fail("Interval must be greater than 0 seconds.", ExitCode.VALIDATION_ERROR)

    path = os.path.abspath(path)
    console.print(
        f"[bold blue]dxcli watch[/bold blue] started. Path: {path}, Interval: {interval}s"
    )
    if threshold_bytes > 0:
        from .outputs.cli_report import format_bytes

        console.print(
            f"[bold red]Alert Threshold active:[/bold red] {format_bytes(threshold_bytes)}/interval"
        )
    console.print("Press Ctrl+C to stop.")

    last_size = None
    iterations = 0
    try:
        while iteration_limit is None or iterations < iteration_limit:
            iterations += 1
            try:
                snap = run_diagnosis(
                    path,
                    scan_threads=scan_threads,
                    nice=nice,
                    ionice=ionice,
                    include_processes=False,
                )
                current_size = sum(d.size_bytes for d in snap.top_dirs)
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
                                console.print(
                                    f"[yellow]Webhook failed: {error}[/yellow]"
                                )
                        if notify_desktop:
                            from .outputs.notifier import send_desktop_notification

                            send_desktop_notification(
                                "dxcli Disk Alert",
                                f"Path '{path}' grew by {format_bytes(delta)}.",
                            )
                last_size = current_size
                console.print(
                    f"[{time.strftime('%H:%M:%S')}] Snapshot: {path} ({len(snap.top_dirs)} dirs tracked){alert_msg}"
                )
            except Exception as exc:
                console.print(
                    f"[yellow]Watch iteration failed: {type(exc).__name__}: {exc}[/yellow]"
                )

            if iteration_limit is not None and iterations >= iteration_limit:
                break
            time.sleep(interval)
    except KeyboardInterrupt as exc:
        raise click.exceptions.Exit(int(ExitCode.INTERRUPTED)) from exc


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="dxcli")
@click.pass_context
def cli(ctx):
    """dxcli - the disk doctor for your CI pipeline and dev box.

    Diagnoses what filled the disk, which process did it, and prescribes
    a fix. Use `dxcli ci` in pipelines, `dxcli diagnose --docker` before
    builds, `dxcli diagnose ~ --classify` on a dev box.
    """
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
@click.option(
    "--report", default=None, help="Generate an HTML report at the specified path."
)
@click.option(
    "--docker",
    is_flag=True,
    help="Include Docker images, containers, volumes, and build cache in the diagnosis (great before `docker build`).",
)
@click.option(
    "--ci",
    is_flag=True,
    help="CI mode: silent on success, exits 1 on critical disk pressure or policy violations. Drop into a pre-build step.",
)
@click.option("--classify", is_flag=True, help="Group disk usage by semantic category.")
@click.option("--target", help="Use a named target defined in config.yaml")
@click.option(
    "--enable-plugins",
    is_flag=True,
    help="Opt-in to execute local plugins from ~/.dx/plugins.",
)
@click.option(
    "--scan-threads",
    type=int,
    default=None,
    help="Max threads to use for scanning directories.",
)
@click.option(
    "--nice", type=int, default=None, help="Set nice priority level (Linux only)."
)
@click.option("--ionice", is_flag=True, help="Set ionice idle priority (Linux only).")
def diagnose(
    path,
    as_json,
    report,
    docker,
    ci,
    classify,
    target,
    enable_plugins,
    scan_threads,
    nice,
    ionice,
):
    """Deep-scan PATH and diagnose what filled it up.

    Common uses:
      dxcli diagnose .            # current dir (default)
      dxcli diagnose . --docker   # include Docker images/cache/volumes
      dxcli diagnose . --ci       # CI mode: exits 1 on critical pressure
      dxcli diagnose ~ --classify # group by category (node_modules, caches, etc.)
    """
    from .engine import run_diagnosis
    from .outputs.cli_report import render_diagnosis
    from .outputs.html_report import generate_html_report

    path, _, _ = resolve_target_config(path, target)
    if not as_json:
        console.print(f"[dim]Scanning {path}...[/dim]", end="\r")

    snap = run_diagnosis(
        path,
        include_docker=docker,
        include_classification=classify,
        include_processes=(not as_json and not ci),
        enable_plugins=enable_plugins,
        scan_threads=scan_threads,
        nice=nice,
        ionice=ionice,
    )

    # -- CI failure check ----------------------------------------------------
    ci_failed = False
    if ci:
        has_critical = any("[CRITICAL]" in alert for alert in snap.anomalies)
        disk_critical = bool(snap.partition and snap.partition.usage_percent >= 90)
        if has_critical or disk_critical:
            ci_failed = True
            if not as_json:
                console.print(
                    "[bold red]CI pipeline failed: disk usage critical or "
                    "policy violation detected.[/bold red]"
                )
                for alert in snap.anomalies:
                    console.print(f"  {alert}")

    # -- JSON output ---------------------------------------------------------
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
            "path": snap.path,
            "partition": asdict(snap.partition) if snap.partition else None,
            "top_dirs": [asdict(item) for item in snap.top_dirs],
            "logs": [asdict(item) for item in snap.logs],
            "stales": [asdict(item) for item in snap.stale_files],
            "trends": snap.trends,
            "prescriptions": [asdict(item) for item in snap.prescriptions],
            "anomalies": snap.anomalies,
            "prediction": asdict(snap.prediction) if snap.prediction else None,
            "classification": snap.classification,
            "ci_failed": ci_failed,
            "collector_errors": [asdict(e) for e in snap.collector_errors],
        }
        print(json.dumps(output, indent=2, cls=DxEncoder))
        if ci_failed:
            raise click.exceptions.Exit(int(ExitCode.CI_FAILURE))
        return

    if ci_failed:
        raise click.exceptions.Exit(int(ExitCode.CI_FAILURE))

    # -- HTML report ---------------------------------------------------------
    if report:
        generate_html_report(
            report,
            snap.path,
            snap.partition,
            snap.top_dirs,
            snap.logs,
            snap.stale_files,
            snap.trends,
            snap.prescriptions,
            snap.prediction,
        )
        console.print(
            f"[bold green]Report generated:[/bold green] {os.path.abspath(report)}"
        )

    # -- CLI report ----------------------------------------------------------
    render_diagnosis(
        snap.path,
        snap.partition,
        snap.top_dirs,
        snap.logs,
        snap.stale_files,
        trends=snap.trends,
        prescriptions=snap.prescriptions,
        anomalies=snap.anomalies,
        prediction=snap.prediction,
        app_accounting=snap.app_accounting,
        classification=snap.classification,
        active_writers=snap.active_writers,
        collector_errors=snap.collector_errors,
    )


@cli.command(name="ci")
@click.argument("path", default=".")
@click.option(
    "--no-docker", is_flag=True, help="Skip Docker analysis (on by default in `ci`)."
)
@click.option(
    "--json", "as_json", is_flag=True, help="Output diagnosis in JSON format."
)
@click.pass_context
def ci_cmd(ctx, path, no_docker, as_json):
    """Shortcut for CI pipelines: `diagnose PATH --ci --docker`.

    Silent on success, exits 1 on critical disk pressure or policy
    violations. Drop in as a pre-build step:

      - name: Disk guard
        run: |
          pip install dxcli
          dxcli ci
    """
    ctx.invoke(
        diagnose,
        path=path,
        as_json=as_json,
        report=None,
        docker=not no_docker,
        ci=True,
        classify=False,
        target=None,
        enable_plugins=False,
        scan_threads=None,
        nice=None,
        ionice=False,
    )


@cli.command()
@click.argument("path", default=".")
@click.option("--hours", default=24, help="Hours back to compare against")
def diff(path, hours):
    """Show what changed since a past snapshot."""
    from .collectors.dir_tree import DirectoryTreeCollector
    from .outputs.cli_report import format_bytes

    path = os.path.abspath(path)
    console.print(
        f"[dim]Calculating diff for {path} vs {hours} hours ago...[/dim]", end="\r"
    )
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
            diffs.append(
                {"path": node.path, "delta": delta, "current": node.size_bytes}
            )
    finally:
        db.close()

    diffs.sort(key=lambda item: abs(item["delta"]), reverse=True)
    table = Table(
        title=f"\n[bold white]DISK DIFF - Last {actual_hours:.1f} Hours[/bold white]",
        box=ROUNDED,
        expand=True,
    )
    table.add_column("Path", style="cyan", no_wrap=True, ratio=4)
    table.add_column("Delta", justify="right", style="bold", ratio=1)
    table.add_column("Current Size", justify="right", style="dim", ratio=1)

    for item in diffs[:10]:
        delta_str = (
            f"+{format_bytes(item['delta'])}"
            if item["delta"] >= 0
            else format_bytes(item["delta"])
        )
        color = "red" if item["delta"] > 0 else "green"
        display_path = (
            item["path"] if len(item["path"]) <= 40 else "..." + item["path"][-37:]
        )
        table.add_row(
            display_path,
            f"[{color}]{delta_str}[/{color}]",
            format_bytes(item["current"]),
        )

    total_color = "red" if total_delta > 0 else "green"
    total_str = (
        f"+{format_bytes(total_delta)}"
        if total_delta >= 0
        else format_bytes(total_delta)
    )
    table.add_row(
        "Total Delta", f"[{total_color}][bold]{total_str}[/bold][/{total_color}]", ""
    )
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

    console.print(
        f"\n[bold white on blue] DISK FORECAST - {partition.mountpoint} [/bold white on blue]"
    )
    gb_total = partition.total_bytes / (1024**3)
    gb_used = partition.used_bytes / (1024**3)
    console.print(
        f"Current:     {gb_used:.1f} GB / {gb_total:.1f} GB ({partition.usage_percent:.1f}%)"
    )

    if result:
        gb_growth = result.daily_growth_bytes / (1024**3)
        accel_str = "(accelerating)" if result.is_accelerating else "(stable)"

        if result.hint == "high variance":
            console.print(f"Growth Rate: {gb_growth:.2f} GB/day (high variance)")
            console.print(
                "\nEstimated Full: [bold yellow]Unpredictable (high variance)[/bold yellow]"
            )
        elif result.days_until_full is not None:
            console.print(f"Growth Rate: {gb_growth:.2f} GB/day {accel_str}")
            if result.days_until_full > 365:
                console.print(
                    "\nEstimated Full: [bold green]Stable (fills in >1 year)[/bold green]"
                )
            elif (
                result.days_until_full_low is not None
                and result.days_until_full_high is not None
            ):
                low = int(round(result.days_until_full_low))
                high = int(round(result.days_until_full_high))
                if high > 365:
                    console.print(
                        f"\nEstimated Full: In [bold red]>= {low} days[/bold red]"
                    )
                else:
                    console.print(
                        f"\nEstimated Full: In [bold red]{low}–{high} days[/bold red]"
                    )
            else:
                console.print(
                    f"\nEstimated Full: In [bold red]{result.days_until_full:.1f} days[/bold red]"
                )
        else:
            console.print(f"Growth Rate: {gb_growth:.2f} GB/day {accel_str}")
            console.print("\nEstimated Full: [bold green]Not growing[/bold green]")
    else:
        console.print("Growth Rate: Static or insufficient history.")
        console.print("\nEstimated Full: [bold green]Not growing[/bold green]")


@cli.command()
@click.argument("path", default=".")
def explain(path):
    """Explain disk usage status and anomalies in plain English."""
    from .engine import run_diagnosis
    from .outputs.cli_report import format_bytes

    path = os.path.abspath(path)
    snap = run_diagnosis(path, include_processes=True)

    # 1. First sentence: Growing path, growth rate, and acceleration
    growing_path = path
    velocity = 0.0
    if snap.trends:
        sorted_trends = sorted(
            snap.trends, key=lambda x: x.get("velocity_per_day", 0.0), reverse=True
        )
        top_trend = sorted_trends[0]
        if top_trend.get("velocity_per_day", 0.0) > 0:
            growing_path = top_trend["path"]
            velocity = top_trend["velocity_per_day"]

    if velocity == 0.0 and snap.prediction and snap.prediction.daily_growth_bytes > 0:
        velocity = snap.prediction.daily_growth_bytes

    if velocity > 0:
        growth_rate_str = f"{format_bytes(int(velocity))}/day"
        if snap.prediction and snap.prediction.is_accelerating:
            acceleration_str = "accelerating"
        else:
            acceleration_str = "stable"
        first_sentence = (
            f"{growing_path} is growing {growth_rate_str}, {acceleration_str}."
        )
    else:
        first_sentence = f"{growing_path} is stable."

    # 2. Second sentence: Culprit attribution
    culprit = None
    if snap.trends:
        sorted_trends = sorted(
            snap.trends, key=lambda x: x.get("velocity_per_day", 0.0), reverse=True
        )
        for t in sorted_trends:
            if t.get("culprit"):
                culprit = t["culprit"]
                break

    if not culprit:
        if snap.active_writers:
            culprit_data = snap.active_writers[0]
            culprit_str = (
                f"PID {culprit_data['pid']} ({culprit_data['name']}) is the writer."
            )
        else:
            culprit_str = "No active writer attributed."
    else:
        culprit_str = f"PID {culprit.pid} ({culprit.name}) is the writer."

    # 3. Third sentence: Forecast until full
    partition = snap.partition
    prediction = snap.prediction
    mountpoint = partition.mountpoint if partition else "/"
    if prediction and prediction.hint == "high variance":
        pred_str = f"At this rate {mountpoint} is stable (unpredictable due to high growth variance)."
    elif prediction and prediction.days_until_full is not None:
        if prediction.days_until_full > 365:
            pred_str = f"At this rate {mountpoint} is stable."
        else:
            if (
                prediction.days_until_full_low is not None
                and prediction.days_until_full_high is not None
            ):
                low = int(round(prediction.days_until_full_low))
                high = int(round(prediction.days_until_full_high))
                if high > 365:
                    pred_str = f"At this rate {mountpoint} fills in >= {low} days."
                elif low == high:
                    pred_str = f"At this rate {mountpoint} fills in {low} days."
                else:
                    pred_str = f"At this rate {mountpoint} fills in {low}–{high} days."
            else:
                pred_str = f"At this rate {mountpoint} fills in {prediction.days_until_full:.1f} days."
    else:
        pred_str = f"At this rate {mountpoint} is stable."

    # 4. Fourth sentence: Root cause
    if snap.logs:
        unrotated_no_config = [
            log_item for log_item in snap.logs if not log_item.has_logrotate_config
        ]
        if unrotated_no_config:
            root_cause_str = "Root cause: no logrotate config."
        else:
            root_cause_str = "Root cause: unrotated log files."
    elif snap.stale_files:
        root_cause_str = "Root cause: stale files accumulating."
    else:
        root_cause_str = "Root cause: general disk usage."

    # 5. Fifth sentence: Fix recommendation
    actionable = [
        p
        for p in snap.prescriptions
        if p.action_type in ("delete", "create_file") and p.target_path
    ]
    if actionable:
        fix_str = "Fix: dxcli heal."
    else:
        fix_str = "Fix: review recommended actions."

    console.print(
        f"{first_sentence} {culprit_str} {pred_str} {root_cause_str} {fix_str}"
    )


@cli.command()
@click.option("--interval", default=300, help="Seconds between snapshots")
@click.option(
    "--alert-threshold",
    default=None,
    help="Alert if growth exceeds threshold (e.g. 100M, 1G)",
)
@click.option(
    "--webhook", default=None, help="Webhook URL to notify on threshold breach"
)
@click.option(
    "--notify-desktop",
    is_flag=True,
    help="Send a desktop notification on threshold breach",
)
@click.option("--target", help="Use a named target defined in config.yaml")
@click.option(
    "--scan-threads",
    type=int,
    default=None,
    help="Max threads to use for scanning directories.",
)
@click.option(
    "--nice", type=int, default=None, help="Set nice priority level (Linux only)."
)
@click.option("--ionice", is_flag=True, help="Set ionice idle priority (Linux only).")
@click.option(
    "--no-tui",
    is_flag=True,
    help="Disable the live TUI dashboard and run as a stdout print loop.",
)
@click.argument("path", default=".")
def watch(
    interval,
    alert_threshold,
    webhook,
    notify_desktop,
    target,
    scan_threads,
    nice,
    ionice,
    no_tui,
    path,
):
    """Continuous monitoring mode. Snapshots disk state periodically."""
    path, target_threshold, target_interval = resolve_target_config(path, target)
    if target_threshold:
        alert_threshold = target_threshold
    if target_interval:
        interval = target_interval
    threshold_bytes = parse_bytes(alert_threshold) if alert_threshold else 0

    use_tui = sys.stdout.isatty() and not no_tui

    if use_tui:
        from .outputs.tui import DxApp

        app = DxApp(
            watch_mode=True,
            path=path,
            interval=interval,
            threshold_bytes=threshold_bytes,
            webhook=webhook,
            notify_desktop=notify_desktop,
            scan_threads=scan_threads,
        )
        app.run()
    else:
        run_watch_loop(
            path,
            interval,
            threshold_bytes,
            webhook,
            notify_desktop,
            scan_threads=scan_threads,
            nice=nice,
            ionice=ionice,
        )


@cli.command()
@click.option("--port", default=8000, help="Metrics server port")
@click.option(
    "--bind",
    default="127.0.0.1",
    help="Address to bind to. Use 0.0.0.0 to expose to network.",
)
@click.option("--interval", default=300, help="Seconds between snapshots")
@click.option(
    "--auth-token", default=None, help="Bearer token for metrics authentication."
)
@click.argument("path", default=".")
def serve(port, bind, interval, auth_token, path):
    """Run dxcli as a metrics-exporting daemon."""
    from .outputs.metrics import create_metrics_server

    bind = validate_bind_address(bind)
    if interval <= 0:
        fail("Interval must be greater than 0 seconds.", ExitCode.VALIDATION_ERROR)

    if bind == "0.0.0.0" and not auth_token:  # nosec B104
        fail(
            "Binding to 0.0.0.0 is refused without --auth-token.",
            ExitCode.UNSAFE_OPERATION,
        )

    if bind == "0.0.0.0":  # nosec B104
        console.print(
            "[bold yellow]WARNING: Binding to 0.0.0.0 exposes metrics to the network.[/bold yellow]"
        )
    try:
        server = create_metrics_server(port, bind, auth_token)
    except OSError as exc:
        fail(
            f"Could not start metrics server on {bind}:{port}: {exc}",
            ExitCode.RUNTIME_ERROR,
        )

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    display_addr = bind if bind != "0.0.0.0" else "localhost"  # nosec B104
    console.print(
        f"[bold green]Sentinel Metrics Server[/bold green] live at http://{display_addr}:{port}/metrics"
    )
    try:
        run_watch_loop(path, interval, 0, None, False)
    finally:
        server.shutdown()
        server.server_close()


@cli.command()
@click.argument("path", default=".")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
@click.option(
    "--dry-run", is_flag=True, help="Simulate healing actions without executing them"
)
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
    actionable = [
        item
        for item in prescriptions
        if item.action_type in ("delete", "create_file") and item.target_path
    ]
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
                console.print(
                    f"  [yellow]Target Path :[/yellow] {prescription.target_path}"
                )
                console.print(
                    f"  [yellow]Savings     :[/yellow] {format_bytes(prescription.size_savings_bytes)}"
                )
                console.print()
            else:
                console.print(
                    f"  [red]Prescription rejected by safety policies:[/red] {prescription.name}\n"
                )
        console.print(
            "[bold green]Dry run completed. No files were modified.[/bold green]"
        )
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

    console.print(
        f"\n[bold green]Healing session complete. {count} actions applied.[/bold green]"
    )
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

    try:
        DxApp().run()
    except (KeyboardInterrupt, SystemExit):
        pass


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

    console.print(
        "  [bold green]Success![/bold green] Running diagnosis on demo sandbox...\n"
    )
    time.sleep(1)
    ctx.invoke(diagnose, path=sandbox_path)


@cli.command(name="snapshot-baseline")
@click.option(
    "--baseline",
    required=True,
    help="Path to output baseline snapshot JSON file.",
)
@click.option("--no-docker", is_flag=True, help="Skip Docker storage collection.")
@click.argument("path", default=".")
def snapshot_baseline(baseline, no_docker, path):
    """Save a pre-build baseline snapshot for post-build autopsy comparison."""
    from .autopsy import save_baseline

    path = os.path.abspath(path)
    try:
        save_baseline(path, baseline, include_docker=not no_docker)
        console.print(
            f"[bold green]Baseline snapshot saved:[/bold green] {os.path.abspath(baseline)}"
        )
    except Exception as exc:
        fail(f"Failed to save baseline snapshot: {exc}", ExitCode.RUNTIME_ERROR)


@cli.command()
@click.option(
    "--baseline",
    required=True,
    help="Path to pre-build baseline snapshot JSON file.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    help="Output format (markdown or json).",
)
@click.option(
    "--summary",
    is_flag=True,
    help="Write markdown summary to $GITHUB_STEP_SUMMARY.",
)
@click.option(
    "--pr-comment",
    is_flag=True,
    help="Post or update single GitHub PR comment.",
)
@click.argument("path", default=".")
def autopsy(baseline, fmt, summary, pr_comment, path):
    """Analyze what grew during a build by comparing against a pre-build baseline."""
    from .autopsy import (
        post_github_pr_comment,
        render_markdown,
        run_autopsy,
        write_github_summary,
    )

    path = os.path.abspath(path)
    try:
        report = run_autopsy(baseline, path)
    except Exception as exc:
        fail(f"Autopsy analysis failed: {exc}", ExitCode.RUNTIME_ERROR)

    if fmt == "json":
        output_dict = {
            "schema": report.schema,
            "created_at": report.created_at,
            "path": report.path,
            "baseline_file": report.baseline_file,
            "total_growth_bytes": report.total_growth_bytes,
            "probable_cause": report.probable_cause,
            "grown_dirs": [asdict(g) for g in report.grown_dirs],
            "shrunk_dirs": [asdict(s) for s in report.shrunk_dirs],
            "docker_growth": report.docker_growth,
            "prescriptions": [asdict(p) for p in report.prescriptions],
            "collector_errors": [asdict(e) for e in report.collector_errors],
        }
        print(json.dumps(output_dict, indent=2))
        return

    markdown = render_markdown(report)
    console.print(markdown)

    if summary:
        wrote = write_github_summary(markdown)
        if wrote:
            console.print("[dim]Summary appended to $GITHUB_STEP_SUMMARY[/dim]")
        else:
            console.print(
                "[yellow]Warning: $GITHUB_STEP_SUMMARY environment variable not set.[/yellow]"
            )

    if pr_comment:
        posted = post_github_pr_comment(markdown)
        if posted:
            console.print(
                "[bold green]GitHub PR comment updated successfully.[/bold green]"
            )
        else:
            console.print(
                "[yellow]Notice: Could not post PR comment (check GITHUB_TOKEN and PR context).[/yellow]"
            )


@cli.command()
@click.option(
    "--dry-run/--no-dry-run",
    default=True,
    help="Preview cleanup plan without removing files (default --dry-run).",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Execute cleanup immediately without interactive confirmation prompt.",
)
@click.option("--no-docker", is_flag=True, help="Skip Docker storage cleanup.")
@click.option(
    "--json", "as_json", is_flag=True, help="Output clean plan or result as JSON."
)
@click.argument("path", default=".")
def clean(dry_run, yes, no_docker, as_json, path):
    """Safely purge disposable caches, build artifacts, and Docker bloat."""
    from .clean_engine import CleanEngine
    from .outputs.cli_report import format_bytes

    engine = CleanEngine()
    plan = engine.create_plan(path, include_docker=not no_docker)

    # If --yes is passed, switch off dry_run unless explicitly specified as --dry-run
    if yes:
        dry_run = False

    if as_json and dry_run:
        output_dict = {
            "dry_run": True,
            "scan_path": plan.scan_path,
            "estimated_savings_bytes": plan.estimated_savings_bytes,
            "targets": [asdict(t) for t in plan.targets],
            "protected_excluded": plan.protected_excluded,
        }
        print(json.dumps(output_dict, indent=2))
        return

    if not plan.targets:
        if not as_json:
            console.print(
                "[bold green]No disposable caches or build artifacts found. System clean![/bold green]"
            )
        return

    # Print CleanPlan table
    if not as_json:
        console.print(
            f"\n[bold white on blue] CLEANUP PLAN ({'DRY-RUN' if dry_run else 'EXECUTION'}) [/bold white on blue]"
        )
        table = Table(box=ROUNDED, expand=True)
        table.add_column("Target", style="cyan")
        table.add_column("Category", style="yellow")
        table.add_column("Estimated Savings", justify="right", style="bold green")

        for target in plan.targets:
            table.add_row(
                target.name,
                target.category,
                format_bytes(target.size_bytes),
            )

        console.print(table)
        console.print(
            f"[bold]Total Estimated Savings:[/bold] [bold green]{format_bytes(plan.estimated_savings_bytes)}[/bold green]"
        )

        if plan.protected_excluded:
            console.print("[dim]Protected / Excluded from deletion:[/dim]")
            for p in plan.protected_excluded:
                console.print(f"  [yellow]• {p}[/yellow]")

    if dry_run:
        if not as_json:
            console.print(
                "\n[bold yellow]Dry-run complete. No files were deleted.[/bold yellow]\n"
                "[dim]To execute cleanup, run:[/dim] [bold white]dxcli clean --yes[/bold white]"
            )
        return

    if not yes:
        if not click.confirm(
            "Are you sure you want to delete these files and prune Docker targets?"
        ):
            console.print("[yellow]Cleanup cancelled.[/yellow]")
            return

    result = engine.execute_plan(plan)

    if as_json:
        print(json.dumps(asdict(result), indent=2))
        return

    console.print(
        f"\n[bold green]Cleanup complete![/bold green] Freed [bold green]{format_bytes(result.freed_bytes)}[/bold green]"
    )
    if result.failed_items:
        console.print("[bold red]Failed items:[/bold red]")
        for item in result.failed_items:
            console.print(f"  [red]• {item['target']}: {item['error']}[/red]")

    console.print(f"[dim]Audit log updated: {result.audit_log_path}[/dim]")


@cli.command()
@click.option(
    "--allow",
    multiple=True,
    help="Allowed directory paths for MCP tool operations (can be specified multiple times).",
)
def mcp(allow):
    """Start MCP (Model Context Protocol) read-only server on stdio for AI agents."""
    from .mcp import McpServer

    allow_list = list(allow) if allow else None
    server = McpServer(allow_paths=allow_list)
    server.run_stdio()


@cli.command()
@click.argument("action", type=click.Choice(["start", "stop", "status"]))
@click.option(
    "--command",
    default="watch",
    type=click.Choice(["watch", "serve"]),
    help="Command to run in background",
)
@click.option("--target", help="Named target to monitor")
@click.option("--notify-desktop", is_flag=True, help="Enable desktop notifications")
@click.option("--webhook", help="Webhook URL to notify")
def daemon(action, command, target, notify_desktop, webhook):
    """Manage dxcli as a background daemon."""
    from .state import atomic_write, get_state_dir

    pid_file = os.path.join(get_state_dir(), f"daemon_{command}.pid")

    if action == "start":
        if os.path.exists(pid_file):
            fail(
                f"Daemon for {command} is already running or PID file exists.",
                ExitCode.UNSAFE_OPERATION,
            )

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
            process = subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        time.sleep(0.2)
        if process.poll() is not None:
            fail(
                f"Daemon process exited during startup with code {process.returncode}.",
                ExitCode.RUNTIME_ERROR,
            )
        atomic_write(pid_file, str(process.pid))
        console.print(
            f"[bold green]Started {command} daemon with PID {process.pid}[/bold green]"
        )
        return

    if action == "stop":
        if not os.path.exists(pid_file):
            fail(f"No daemon running for {command}.", ExitCode.RUNTIME_ERROR)
        try:
            with open(pid_file, "r", encoding="utf-8") as handle:
                pid = int(handle.read().strip())
        except Exception as exc:
            fail(
                f"Failed to read PID file. It may be corrupted: {exc}",
                ExitCode.RUNTIME_ERROR,
            )
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    check=False,
                )
            else:
                os.kill(pid, signal.SIGTERM)
            console.print(
                f"[bold green]Stopped {command} daemon (PID {pid}).[/bold green]"
            )
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
        fail(
            f"psutil is required for daemon status checks: {exc}",
            ExitCode.RUNTIME_ERROR,
        )

    if not os.path.exists(pid_file):
        fail(f"Daemon {command} is not running.", ExitCode.RUNTIME_ERROR)
    try:
        with open(pid_file, "r", encoding="utf-8") as handle:
            pid = int(handle.read().strip())
        if psutil.pid_exists(pid):
            console.print(
                f"[bold green]Daemon {command} is RUNNING (PID {pid})[/bold green]"
            )
            return
        console.print(
            f"[yellow]Daemon {command} is NOT running (stale PID {pid}).[/yellow]"
        )
        try:
            os.remove(pid_file)
        except OSError:
            pass
        fail(f"Daemon {command} is not running.", ExitCode.RUNTIME_ERROR)
    except ValueError:
        fail("Daemon PID file is corrupted.", ExitCode.RUNTIME_ERROR)


@cli.command()
@click.argument("path", default=".")
@click.option(
    "--json", "as_json", is_flag=True, help="Emit fleet-ready host telemetry as JSON."
)
@click.option(
    "--max-items",
    default=100,
    show_default=True,
    help="Maximum top dirs, logs, and stale files in output.",
)
@click.option(
    "--push",
    default=None,
    help="V1 receiver snapshot URL (e.g. http://localhost:8080/v1/snapshots)",
)
@click.option("--token", default=None, help="Bearer authorization token.")
@click.option(
    "--anonymize",
    is_flag=True,
    help="Anonymize user directories and hostname in telemetry.",
)
def snapshot(path, as_json, max_items, push, token, anonymize):
    """Collect a fleet-ready local host telemetry snapshot."""
    from .enterprise import AgentSnapshotCollector
    from .outputs.cli_report import format_bytes

    if max_items < 1:
        fail("--max-items must be greater than 0.", ExitCode.VALIDATION_ERROR)

    if push and not token:
        token = os.environ.get("DX_API_TOKEN")
        if not token:
            fail(
                "Providing a --push URL requires --token or env DX_API_TOKEN.",
                ExitCode.VALIDATION_ERROR,
            )

    snapshot_data = AgentSnapshotCollector().collect(path, anonymize=anonymize)
    snapshot_data.top_dirs = snapshot_data.top_dirs[:max_items]
    snapshot_data.logs = snapshot_data.logs[:max_items]
    snapshot_data.stales = snapshot_data.stales[:max_items]
    snapshot_data.risk_signals = snapshot_data.risk_signals[:max_items]

    if push:
        from .outputs.notifier import (
            validate_webhook_destination,
            NoRedirectHandler,
            PinnedHTTPHandler,
            PinnedHTTPSHandler,
        )
        import ssl
        import urllib.request
        import urllib.error

        is_valid, error, pinned_ip = validate_webhook_destination(
            push, allow_private=(os.environ.get("DX_ALLOW_PRIVATE_INGEST") == "1")
        )
        if not is_valid:
            fail(f"Invalid push destination URL: {error}", ExitCode.VALIDATION_ERROR)

        payload_bytes = json.dumps(asdict(snapshot_data)).encode("utf-8")
        req = urllib.request.Request(
            push,
            data=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"dxcli-agent/{__version__}",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )

        context = ssl.create_default_context()
        handlers = [
            NoRedirectHandler(),
            PinnedHTTPHandler(pinned_ip),
            PinnedHTTPSHandler(pinned_ip, context=context),
        ]
        opener = urllib.request.build_opener(*handlers)

        max_retries = 3
        backoff = 0.5
        last_error = None

        for attempt in range(max_retries):
            try:
                with opener.open(req, timeout=10.0) as response:
                    if response.status in (200, 201, 202, 204):
                        if as_json:
                            print(json.dumps(asdict(snapshot_data), indent=2))
                        else:
                            console.print(
                                f"[bold green]Snapshot successfully pushed to {push}[/bold green]"
                            )
                        return
                    if response.status not in (429, 502, 503, 504):
                        fail(
                            f"Push failed with HTTP status: {response.status}",
                            ExitCode.RUNTIME_ERROR,
                        )
                    last_error = f"HTTP {response.status}"
            except urllib.error.HTTPError as e:
                if e.code not in (429, 502, 503, 504):
                    fail(
                        f"Push failed with HTTP status: {e.code}",
                        ExitCode.RUNTIME_ERROR,
                    )
                last_error = f"HTTP {e.code}"
            except urllib.error.URLError as e:
                last_error = f"Network error: {e.reason}"
            except Exception as e:
                last_error = f"Error: {e}"

            if attempt < max_retries - 1:
                time.sleep(backoff * (2**attempt))

        fail(
            f"Push failed after {max_retries} attempts: {last_error}",
            ExitCode.RUNTIME_ERROR,
        )

    if as_json:
        print(json.dumps(asdict(snapshot_data), indent=2))
        return

    console.print("[bold blue]Host Storage Snapshot[/bold blue]")
    console.print(f"Host: {snapshot_data.hostname}")
    console.print(
        f"Risk: [bold]{snapshot_data.risk_level}[/bold] ({snapshot_data.risk_score})"
    )
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
        for sig in snapshot_data.risk_signals[:10]:
            signal_table.add_row(
                sig.severity, sig.category, str(sig.score), sig.message
            )
        console.print(signal_table)


@cli.command()
@click.argument("hosts", nargs=-1)
@click.option("--port", default=8000, help="Port of dxcli serve instances")
@click.option(
    "--server",
    default=None,
    help="Fleet receiver server URL (e.g. http://localhost:8080)",
)
@click.option("--token", default=None, help="Auth token for fleet server")
def fleet(hosts, port, server, token):
    """Aggregate metrics from multiple dxcli serve instances or a fleet server."""
    import urllib.error
    import urllib.request
    import json

    if not server and not hosts:
        fail(
            "Usage: dxcli fleet host1 host2 ... OR dxcli fleet --server <url>",
            ExitCode.VALIDATION_ERROR,
        )

    if server:
        if not token:
            token = os.environ.get("DX_API_TOKEN")
        if not token:
            fail(
                "dxcli fleet --server requires --token or env DX_API_TOKEN.",
                ExitCode.VALIDATION_ERROR,
            )

        from .outputs.notifier import (
            validate_webhook_destination,
            NoRedirectHandler,
            PinnedHTTPHandler,
            PinnedHTTPSHandler,
        )
        import ssl

        url = f"{server.rstrip('/')}/v1/fleet/status"
        is_valid, error, pinned_ip = validate_webhook_destination(
            url, allow_private=(os.environ.get("DX_ALLOW_PRIVATE_INGEST") == "1")
        )
        if not is_valid:
            fail(f"Invalid fleet server URL: {error}", ExitCode.VALIDATION_ERROR)

        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "dxcli-agent",
            },
            method="GET",
        )
        if token:
            req.add_header("Authorization", f"Bearer {token}")

        context = ssl.create_default_context()
        handlers = [
            NoRedirectHandler(),
            PinnedHTTPHandler(pinned_ip),
            PinnedHTTPSHandler(pinned_ip, context=context),
        ]
        opener = urllib.request.build_opener(*handlers)

        try:
            with opener.open(req, timeout=5.0) as response:
                if response.status != 200:
                    fail(
                        f"Fleet server query failed with HTTP status: {response.status}",
                        ExitCode.RUNTIME_ERROR,
                    )
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as e:
            fail(
                f"Fleet query failed (network error): {e.reason}",
                ExitCode.RUNTIME_ERROR,
            )
        except Exception as e:
            fail(f"Fleet query failed (error): {e}", ExitCode.RUNTIME_ERROR)

        table = Table(
            title="[bold white]dxcli Central Fleet Dashboard[/bold white]", box=ROUNDED
        )
        table.add_column("Host", style="cyan")
        table.add_column("Partition", style="white")
        table.add_column("Usage", justify="right")
        table.add_column("Status", justify="center")

        for host_info in data.get("hosts", []):
            host_name = host_info.get("hostname", "unknown")
            partitions = host_info.get("partitions", [])
            risk_level = host_info.get("risk_level", "healthy")

            status_color = (
                "red"
                if risk_level == "critical"
                else "yellow" if risk_level == "warning" else "green"
            )
            status_str = f"[{status_color}]{risk_level.upper()}[/{status_color}]"

            if not partitions:
                table.add_row(host_name, "---", "---", status_str)
            for part in partitions:
                usage = part.get("usage_percent", 0.0)
                usage_color = (
                    "red" if usage > 90 else "yellow" if usage > 75 else "green"
                )
                table.add_row(
                    host_name,
                    part.get("mountpoint", "/"),
                    f"[{usage_color}]{usage:.1f}%[/{usage_color}]",
                    status_str,
                )

        console.print(table)
        return

    table = Table(title="[bold white]dxcli Fleet Dashboard[/bold white]", box=ROUNDED)
    table.add_column("Host", style="cyan")
    table.add_column("Partition", style="white")
    table.add_column("Usage", justify="right")
    table.add_column("Status", justify="center")

    for host in hosts:
        url = f"http://{host}:{port}/metrics"
        try:
            with urllib.request.urlopen(url, timeout=3) as response:  # nosec B310
                content = response.read().decode("utf-8")
            metrics = {}
            for line in content.splitlines():
                if line.startswith("dx_partition_usage_percent"):
                    parts = line.split()
                    metrics[parts[0].split('"')[1]] = parts[1]
            for mount, usage in metrics.items():
                color = (
                    "red"
                    if float(usage) > 90
                    else "yellow" if float(usage) > 75 else "green"
                )
                table.add_row(
                    host,
                    mount,
                    f"[{color}]{usage}%[/{color}]",
                    "[bold green]ONLINE[/bold green]",
                )
        except urllib.error.URLError as exc:
            table.add_row(
                host, "---", "---", f"[bold red]OFFLINE[/bold red] ({exc.reason})"
            )
        except Exception as exc:
            table.add_row(
                host, "---", "---", f"[bold red]ERROR[/bold red] ({type(exc).__name__})"
            )

    console.print(table)


@cli.command()
def add_target():
    """Interactively add a named target to the configuration."""
    from .config import TargetConfig

    name = click.prompt("Name for this target")
    path = click.prompt("Path to monitor", default=os.getcwd())
    threshold = click.prompt(
        "Alert threshold (e.g. 10GB)", default="", show_default=False
    )
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
        fail(
            "Service generation is currently only optimized for Linux (systemd).",
            ExitCode.RUNTIME_ERROR,
        )
    config = get_config()
    if not target or target not in config.targets:
        fail(
            "Please specify a valid --target defined in config.yaml",
            ExitCode.VALIDATION_ERROR,
        )

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
            console.print(
                "[bold green]Plugin successfully added to allowlist.[/bold green]"
            )
        except OSError as e:
            fail(f"Failed to write to allowlist: {e}", ExitCode.RUNTIME_ERROR)


def main():
    try:
        cli(standalone_mode=False)
    except (KeyboardInterrupt, click.exceptions.Abort):
        console.print("\n[yellow]Operation cancelled by user.[/yellow]")
        sys.exit(130)
    except click.exceptions.ClickException as e:
        e.show()
        sys.exit(e.exit_code)
    except DxCliError as e:
        console.print(f"[bold red]Error:[/bold red] {e.message}")
        sys.exit(int(e.code))
    except Exception as e:
        console.print(f"[bold red]Unexpected Error:[/bold red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
