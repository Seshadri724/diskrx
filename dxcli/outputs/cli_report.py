import sys
import os

# Force UTF-8 on Windows to prevent encoding errors with Unicode box chars
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.box import DOUBLE, ROUNDED
from typing import Dict, List
from ..store.models import DirNode, UnrotatedLog, StaleFile, Partition, Prescription

console = Console(force_terminal=True)


def format_bytes(b: int) -> str:
    if b < 0:
        return f"-{format_bytes(-b)}"
    if b >= 1024**3:
        return f"{b / (1024**3):.1f} GB"
    elif b >= 1024**2:
        return f"{b / (1024**2):.1f} MB"
    elif b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b} B"


def sparkline_str(values: list, width: int = 6) -> str:
    """Render a list of numeric values as a Unicode sparkline."""
    if not values or len(values) < 2:
        return "──────"
    blocks = " ▁▂▃▄▅▆▇█"
    mn = min(values)
    mx = max(values)
    spread = mx - mn
    recent = values[-width:]
    if spread == 0:
        return "▃" * len(recent)
    result = ""
    for v in recent:
        idx = int(((v - mn) / spread) * (len(blocks) - 1))
        result += blocks[idx]
    return result


def trend_label(velocity: float) -> str:
    """Convert a velocity to a human-readable trend label."""
    if velocity > 1024 * 1024 * 50:
        return "[bold red]SPIKE[/bold red]"
    elif velocity > 1024 * 1024 * 5:
        return "[yellow]GROWING[/yellow]"
    elif velocity < -1024 * 1024:
        return "[cyan]SHRINK[/cyan]"
    elif velocity == 0:
        return "[dim]STALE[/dim]"
    else:
        return "[green]STABLE[/green]"


def severity_bar(percent: float, width: int = 32) -> str:
    """Create a colored progress bar based on disk usage severity."""
    filled = int((percent / 100) * width)
    empty = width - filled

    if percent >= 90:
        color = "red"
        label = "CRITICAL"
    elif percent >= 75:
        color = "yellow"
        label = "WARNING"
    else:
        color = "green"
        label = "HEALTHY"

    bar = f"[{color}]{'█' * filled}[/{color}][dim]{'░' * empty}[/dim]"
    return bar, label, color


def render_diagnosis(
    path: str,
    partition: Partition,
    top_dirs: List[DirNode],
    logs: List[UnrotatedLog],
    stales: List[StaleFile],
    trends: List[dict] = None,
    prescriptions: List[Prescription] = None,
    anomalies: List[str] = None,
    prediction=None,
    app_accounting: List[dict] = None,
    classification: Dict[str, int] = None,
    active_writers: List[dict] = None,
    collector_errors: List = None,
):

    trend_info = {t["path"]: t for t in trends} if trends else {}

    # ── HEADER ───────────────────────────────────────────
    console.print()
    console.print(
        Panel(
            Text.from_markup(
                f"[bold white]DISK INTELLIGENCE REPORT[/bold white]\n[dim]{path}[/dim]"
            ),
            box=ROUNDED,
            style="blue",
            expand=False,
        )
    )

    # ── 1. ACTION HEADER (PRESCRIPTION FIRST) ────────────────
    if prescriptions:
        actionable_prescriptions = [
            pr
            for pr in prescriptions
            if pr.action_type in ("delete", "create_file") and pr.target_path
        ]
        if actionable_prescriptions:
            p = actionable_prescriptions[0]  # Focus on the most impactful action
            total_savings = sum(
                pr.size_savings_bytes for pr in actionable_prescriptions
            )

            action_text = Text.from_markup(
                f"  [bold red][!] ACTION REQUIRED[/bold red]\n"
                f"  [bold]Primary Fix:[/bold] [yellow]{p.name}[/yellow]\n"
                f"  [dim]Reclaim {format_bytes(total_savings)} across {len(actionable_prescriptions)} items.[/dim]\n"
                f"  [bold]Run:[/bold] [white on red] dxcli heal [/white on red]"
            )
            console.print(
                Panel(action_text, box=DOUBLE, border_style="red", padding=(1, 2))
            )
        else:
            p = prescriptions[0]
            action_text = Text.from_markup(
                f"  [bold yellow][i] RECOMMENDATION[/bold yellow]\n"
                f"  [bold]Manual Fix:[/bold] [yellow]{p.name}[/yellow]\n"
                f"  [dim]{p.description}[/dim]\n"
                f"  [bold]Command:[/bold] [white on black] {p.template} [/white on black]"
            )
            console.print(
                Panel(action_text, box=ROUNDED, border_style="yellow", padding=(1, 2))
            )

    # ── 2. MINIMALIST STATUS ───────────────────────────────
    if partition:
        bar, label, color = severity_bar(partition.usage_percent, width=24)

        pred_str = ""
        if prediction and prediction.days_until_full is not None:
            days = prediction.days_until_full
            if days < 7:
                pred_str = (
                    f"[!!] Full in [bold blink red]{days:.1f} days[/bold blink red]"
                )
            else:
                pred_str = f"[~] Full in [bold yellow]{days:.0f} days[/bold yellow]"
        else:
            pred_str = "[dim]Growth stable[/dim]"

        status_line = Text.from_markup(
            f"  [bold cyan]Partition:[/bold cyan] {partition.mountpoint:<6} [bold white]{partition.usage_percent:>3.0f}%[/bold white] {bar} {pred_str}"
        )
        console.print(status_line)

    # ── 3. DIAGNOSTIC NARRATIVE ───────────────────────────
    if trends and len(trends) > 0:
        fastest = max(trends, key=lambda t: t.get("velocity_per_day", 0))
        vel = fastest.get("velocity_per_day", 0)

        if vel > 1024 * 1024:  # > 1MB/day
            culprit = fastest.get("culprit")
            proc_str = (
                f" ([bold magenta]PID {culprit.pid} - {culprit.name}[/bold magenta])"
                if culprit
                else ""
            )

            console.print(
                f"\n  [bold red]●[/bold red] [bold underline]Primary Culprit:[/bold underline] {os.path.basename(fastest['path'])}"
            )
            console.print(f"    [dim]{fastest['path']}[/dim]")
            console.print(
                f"    ↳ Growing at [bold red]{format_bytes(vel)}/day[/bold red]{proc_str}"
            )

    # ── 4. SENTINEL ALERTS ────────────────────────────────
    if anomalies:
        for a in anomalies:
            console.print(f"  [bold red][!] SENTINEL:[/bold red] {a}")

    # ── 4.5 COLLECTOR WARNINGS ───────────────────────────
    if collector_errors:
        for err in collector_errors[:5]:
            err_msg = getattr(err, "message", str(err))
            err_path = getattr(err, "path", None)
            path_str = f" at {err_path}" if err_path else ""
            console.print(
                f"  [bold yellow][!] SCAN WARNING:[/bold yellow] {err_msg}{path_str}"
            )
        if len(collector_errors) > 5:
            console.print(
                f"  [dim]... and {len(collector_errors) - 5} more scan warning(s).[/dim]"
            )

    # ── 5. CONSUMER INSIGHTS ──────────────────────────────
    table = Table(
        box=ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        expand=True,
        padding=(0, 1),
        title="\n[dim]Top Storage Consumers[/dim]",
    )
    table.add_column("Path", style="white", no_wrap=True, ratio=4)
    table.add_column("Size", justify="right", style="bold white", ratio=1)
    table.add_column("Trend", justify="center", ratio=2)

    for d in top_dirs[:5]:
        info = trend_info.get(d.path, {})
        vel = info.get("velocity_per_day", 0)
        spark = sparkline_str(info.get("history", []))
        label = trend_label(vel)

        # Truncate long paths for the table
        display_path = d.path
        if len(display_path) > 40:
            display_path = "..." + display_path[-37:]

        table.add_row(display_path, format_bytes(d.size_bytes), f"{spark} {label}")

    console.print(table)

    # ── 5.5 APPLICATION FOOTPRINT ──────────────────────────
    if app_accounting:
        app_table = Table(
            box=ROUNDED,
            show_header=True,
            header_style="bold magenta",
            border_style="dim",
            expand=True,
            padding=(0, 1),
            title="\n[dim]Top Storage Consumers by Application (Open Files)[/dim]",
        )
        app_table.add_column("Application (Process)", style="white", ratio=3)
        app_table.add_column(
            "Active Footprint", justify="right", style="bold white", ratio=1
        )

        for app in app_accounting[:5]:
            pids_str = ", ".join(map(str, app["pids"][:3]))
            if len(app["pids"]) > 3:
                pids_str += ", ..."
            app_table.add_row(
                f"{app['name']} [dim](PIDs: {pids_str})[/dim]",
                format_bytes(app["total_bytes"]),
            )

        console.print(app_table)

    # ── 5.6 SEMANTIC CATEGORIZATION ────────────────────────
    if classification:
        class_table = Table(
            box=ROUNDED,
            show_header=True,
            header_style="bold green",
            border_style="dim",
            expand=True,
            padding=(0, 1),
            title="\n[dim]Semantic Usage (by Content Type)[/dim]",
        )
        class_table.add_column("Category", style="white", ratio=3)
        class_table.add_column(
            "Total Size", justify="right", style="bold white", ratio=1
        )

        # Sort by size descending
        sorted_cats = sorted(classification.items(), key=lambda x: x[1], reverse=True)
        for cat, size in sorted_cats:
            if size > 0:
                class_table.add_row(cat, format_bytes(size))

        console.print(class_table)

    # ── 5.7 ACTIVE WRITERS ────────────────────────────────
    if active_writers:
        writer_table = Table(
            box=ROUNDED,
            show_header=True,
            header_style="bold red",
            border_style="dim",
            expand=True,
            padding=(0, 1),
            title="\n[dim]Active Writers (Detected Throughput)[/dim]",
        )
        writer_table.add_column("Process", style="white", ratio=3)
        writer_table.add_column(
            "Throughput", justify="right", style="bold red", ratio=1
        )

        for w in active_writers:
            writer_table.add_row(
                f"{w['name']} [dim](PID: {w['pid']})[/dim]",
                f"{format_bytes(int(w['throughput_bps']))}/s",
            )

        console.print(writer_table)

    # ── 6. ALL CLEAR FOOTER ──────────────────────────────
    if not prescriptions and not logs and not stales:
        console.print(
            "  [bold green][OK] ALL CLEAR[/bold green] -- No immediate threats detected."
        )

    # ── 7. INSTALL INSTRUCTIONS FOR GENERATED CONFIGS ────
    if prescriptions:
        create_files = [pr for pr in prescriptions if pr.action_type == "create_file"]
        if create_files:
            console.print(
                "\n  [bold yellow][i] INSTALL INSTRUCTIONS FOR GENERATED CONFIGS[/bold yellow]"
            )
            for pr in create_files:
                basename = os.path.basename(pr.target_path)
                system_path = f"/etc/logrotate.d/{basename}"
                console.print(
                    "    - To install the generated logrotate configuration, copy it to the target path:"
                )
                console.print(
                    f"      [bold white]sudo cp {pr.target_path} {system_path}[/bold white]"
                )

    console.print()
