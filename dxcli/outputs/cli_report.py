import sys
import os

# Force UTF-8 on Windows to prevent encoding errors with Unicode box chars
if sys.platform == 'win32':
    os.environ.setdefault('PYTHONUTF8', '1')
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from rich.box import DOUBLE, ROUNDED
from typing import List, Optional
from ..store.models import DirNode, UnrotatedLog, StaleFile, Partition, Prescription

console = Console(force_terminal=True)

def format_bytes(b: int) -> str:
    if b < 0:
        return f"-{format_bytes(-b)}"
    if b >= 1024 ** 3:
        return f"{b / (1024**3):.1f} GB"
    elif b >= 1024 ** 2:
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

def render_diagnosis(path: str, 
                      partition: Partition, 
                      top_dirs: List[DirNode], 
                      logs: List[UnrotatedLog], 
                      stales: List[StaleFile],
                      trends: List[dict] = None,
                      prescriptions: List[Prescription] = None,
                      anomalies: List[str] = None,
                      prediction = None):
    
    trend_info = {t['path']: t for t in trends} if trends else {}
    
    # ── HEADER ────────────────────────────────────────────
    header_parts = []
    if partition:
        bar, label, color = severity_bar(partition.usage_percent)
        
        pred_str = ""
        if prediction and prediction.days_until_full is not None:
            days = prediction.days_until_full
            if days < 1:
                pred_str = f"Full in [bold red]{days*24:.0f}h[/bold red]"
            elif days < 7:
                d = int(days)
                h = int((days - d) * 24)
                pred_str = f"Full in [bold red]{d}d {h}h[/bold red]"
            else:
                pred_str = f"Full in [bold yellow]{days:.0f} days[/bold yellow]"
        else:
            pred_str = "[green]Not growing[/green]"
        
        header = Text.from_markup(
            f"  [bold]dxcli — Disk Diagnosis[/bold]"
            f"{'':>20}"
            f"{partition.mountpoint}  {partition.usage_percent:.0f}%\n"
            f"  {bar}  [{color}]{label}[/{color}] — {pred_str}"
        )
    else:
        header = Text.from_markup(f"  [bold]dxcli — Disk Diagnosis[/bold]  {path}")
    
    console.print()
    console.print(Panel(header, box=DOUBLE, style="bold blue"))
    
    # ── ROOT CAUSE ──────────────────────────────────────
    if trends and len(trends) > 0:
        # Find the fastest-growing directory
        fastest = max(trends, key=lambda t: t.get('velocity_per_day', 0))
        vel = fastest.get('velocity_per_day', 0)
        
        if vel > 1024 * 1024:  # > 1MB/day growth
            culprit = fastest.get('culprit')
            proc_str = f" (written by [bold]{culprit.name}[/bold])" if culprit else ""
            
            # Check if it's an unrotated log
            log_match = None
            for log in logs:
                if log.path.startswith(fastest['path']):
                    log_match = log
                    break
            
            cause_lines = f"  [bold red]🔴 ROOT CAUSE IDENTIFIED[/bold red]\n"
            if log_match and not log_match.has_logrotate_config:
                cause_lines += f"  {fastest['path']} — {format_bytes(fastest['current_size'])} (no rotation configured){proc_str}\n"
            else:
                cause_lines += f"  {fastest['path']} — {format_bytes(fastest['current_size'])}{proc_str}\n"
            cause_lines += f"  Growing at {format_bytes(vel)}/day"
            
            console.print(Panel(Text.from_markup(cause_lines), box=ROUNDED, border_style="red"))
    
    # ── ANOMALY ALERTS ──────────────────────────────────
    if anomalies:
        for a in anomalies:
            console.print(f"  [bold red]⚠ SENTINEL:[/bold red] {a}")
        console.print()
    
    # ── TOP CONSUMERS TABLE ─────────────────────────────
    table = Table(
        title="TOP CONSUMERS", 
        box=ROUNDED,
        show_header=True, 
        header_style="bold white",
        border_style="blue",
        title_style="bold blue",
        pad_edge=True,
        expand=True
    )
    table.add_column("Path", style="cyan", no_wrap=True, max_width=40, ratio=4)
    table.add_column("Size", justify="right", style="bold white", no_wrap=True, ratio=1)
    table.add_column("Growth/Day", justify="right", no_wrap=True, ratio=1)
    table.add_column("Trend", justify="center", no_wrap=True, ratio=2)
    table.add_column("Process", style="dim", no_wrap=True, ratio=2)
    
    for d in top_dirs[:8]:
        info = trend_info.get(d.path, {})
        vel = info.get('velocity_per_day', 0)
        culprit = info.get('culprit')
        proc_str = f"{culprit.name}" if culprit else "-"
        
        # Growth rate with color
        if vel > 1024 * 1024 * 50:
            growth_str = f"[bold red]+{format_bytes(vel)}/d[/bold red]"
        elif vel > 1024 * 1024:
            growth_str = f"[yellow]+{format_bytes(vel)}/d[/yellow]"
        elif vel > 0:
            growth_str = f"[green]+{format_bytes(vel)}/d[/green]"
        else:
            growth_str = f"[dim]0 B/d[/dim]"
        
        # Sparkline + label
        spark = sparkline_str(info.get('history', []))
        label = trend_label(vel)
        trend_display = f"{spark} {label}"
        
        table.add_row(d.path, format_bytes(d.size_bytes), growth_str, trend_display, proc_str)
        
    console.print(table)
    
    # ── PRESCRIPTIONS ───────────────────────────────────
    if prescriptions:
        presc_table = Table(
            title="💊 PRESCRIPTIONS",
            box=ROUNDED,
            show_header=True,
            header_style="bold white",
            border_style="yellow",
            title_style="bold yellow",
            expand=True
        )
        presc_table.add_column("#", style="bold yellow", width=3)
        presc_table.add_column("Action", style="white", ratio=5)
        presc_table.add_column("Risk", justify="center", ratio=1)
        presc_table.add_column("Est. Savings", justify="right", style="bold green", ratio=1)
        
        total_savings = 0
        for i, p in enumerate(prescriptions, 1):
            risk_color = "green" if p.risk == "safe" else "yellow"
            presc_table.add_row(
                f"[{i}]", 
                p.name, 
                f"[{risk_color}]{p.risk}[/{risk_color}]",
                f"-{format_bytes(p.size_savings_bytes)}"
            )
            total_savings += p.size_savings_bytes
            
        console.print(presc_table)
        console.print(f"  [bold green]Total recoverable: {format_bytes(total_savings)}[/bold green]")
    
    # ── PROBLEMS (logs/stales not in prescriptions) ─────
    if not prescriptions and (logs or stales):
        console.print(f"\n  [bold red]⚠ PROBLEMS FOUND[/bold red]")
        for log in logs[:5]:
            rot_str = ", [bold red]NO ROTATION[/bold red]" if not log.has_logrotate_config else ""
            console.print(f"  [LOG] {log.path} — {format_bytes(log.size_bytes)}{rot_str}")
        for stale in stales[:5]:
            console.print(f"  [STALE] {stale.path} — {format_bytes(stale.size_bytes)}, {stale.days_stale:.0f}d old")
    
    if not prescriptions and not logs and not stales:
        console.print(f"\n  [bold green]✅ ALL CLEAR — No issues found.[/bold green]")
    
    console.print()
