from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Static, Label, LoadingIndicator
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual import work

from ..platform import provider
from ..store.models import Partition
from ..outputs.cli_report import format_bytes
from rich.text import Text

import os

# ── Midnight palette (kept in sync with tui.tcss) ────────────────────────────
C_CYAN = "#22D3EE"
C_GREEN = "#34D399"
C_AMBER = "#FBBF24"
C_RED = "#F87171"
C_PURPLE = "#A78BFA"
C_TEXT = "#E6EDF3"
C_MUTED = "#6E7681"


def _usage_color(pct: float) -> str:
    """Green under 70%, amber to 90%, red beyond — instant visual triage."""
    if pct >= 90:
        return C_RED
    if pct >= 70:
        return C_AMBER
    return C_GREEN


def _urgency_color(days) -> str:
    """Colour a 'days until full' forecast by how soon it bites."""
    if days is None:
        return C_MUTED
    if days <= 30:
        return C_RED
    if days <= 90:
        return C_AMBER
    return C_GREEN


def _trend_glyph(trend_str: str):
    """Map a trend label to an arrow + colour."""
    t = (trend_str or "").lower()
    if any(k in t for k in ("grow", "rising", "up", "increas")):
        return "↑", C_RED
    if any(k in t for k in ("shrink", "falling", "down", "decreas")):
        return "↓", C_GREEN
    return "→", C_MUTED


def sparkline_str(values: list, width: int = 10) -> str:
    """Render a list of numeric values as a string-based sparkline using Unicode block chars."""
    if not values or len(values) < 2:
        return "—"

    blocks = " ▁▂▃▄▅▆▇█"
    mn = min(values)
    mx = max(values)
    spread = mx - mn

    # Take last `width` values
    recent = values[-width:]

    if spread == 0:
        return blocks[1] * len(recent)  # Flat line

    result = ""
    for v in recent:
        idx = int(((v - mn) / spread) * (len(blocks) - 1))
        result += blocks[idx]
    return result


class PartitionPanel(Static):
    partitions = reactive([])

    def compose(self) -> ComposeResult:
        yield Label("PARTITIONS", classes="header-text")
        self.display_label = Label("Loading...")
        yield self.display_label

    def watch_partitions(self, parts: list[Partition]) -> None:
        out_str = ""
        is_sr = getattr(self, "app", None) and getattr(self.app, "screen_reader", False)
        for p in parts:
            if is_sr:
                out_str += f"{p.mountpoint:<6}: {p.usage_percent:.1f}% full\n"
            else:
                width = 20
                pct = p.usage_percent
                filled = int((pct / 100) * width)
                bar = ("█" * filled) + ("░" * (width - filled))
                color = _usage_color(pct)
                out_str += (
                    f"[{C_MUTED}]{p.mountpoint:<6}[/] "
                    f"[{color}]{bar}[/] "
                    f"[{color} bold]{pct:5.1f}%[/]\n"
                )
        self.display_label.update(out_str if out_str else "No partitions found.")


class PredictionPanel(Static):
    prediction_text = reactive("Run scan to calculate...")

    def compose(self) -> ComposeResult:
        yield Label("FORECAST", classes="header-text")
        self.display_label = Label(self.prediction_text)
        yield self.display_label

    def watch_prediction_text(self, text: str) -> None:
        if hasattr(self, "display_label"):
            self.display_label.update(text)


class ProblemsPanel(Static):
    problems_text = reactive("Waiting for deep scan...")

    def compose(self) -> ComposeResult:
        yield Label("ISSUES", classes="header-text")
        self.display_label = Label(self.problems_text)
        yield self.display_label

    def watch_problems_text(self, text: str) -> None:
        if hasattr(self, "display_label"):
            self.display_label.update(text)


class PrescriptionsPanel(Static):
    prescriptions_text = reactive("Press [d] to scan...")

    def compose(self) -> ComposeResult:
        yield Label("PRESCRIPTIONS", classes="header-text")
        self.display_label = Label(self.prescriptions_text)
        yield self.display_label

    def watch_prescriptions_text(self, text: str) -> None:
        if hasattr(self, "display_label"):
            self.display_label.update(text)


class AnomalyPanel(Static):
    anomaly_text = reactive(f"[{C_GREEN}]● Sentinel: Systems Nominal[/]")

    def compose(self) -> ComposeResult:
        yield Label("SENTINEL", classes="header-text")
        self.display_label = Label(self.anomaly_text)
        yield self.display_label

    def watch_anomaly_text(self, text: str) -> None:
        if hasattr(self, "display_label"):
            self.display_label.update(text)
            if "Nominal" not in text:
                self.add_class("pulse-warning")
            else:
                self.remove_class("pulse-warning")


class ActiveWritersPanel(Static):
    writers_text = reactive("Run scan to see throughput...")

    def compose(self) -> ComposeResult:
        yield Label("WRITERS", classes="header-text")
        self.display_label = Label(self.writers_text)
        yield self.display_label

    def watch_writers_text(self, text: str) -> None:
        if hasattr(self, "display_label"):
            self.display_label.update(text)


class DxApp(App):
    CSS_PATH = "tui.tcss"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("d", "diagnose", "Scan"),
        ("r", "refresh", "Refresh Partitions"),
    ]

    is_scanning = reactive(False)

    def __init__(
        self,
        watch_mode: bool = False,
        path: str = None,
        interval: float = 300.0,
        threshold_bytes: int = 0,
        webhook: str = None,
        notify_desktop: bool = False,
        scan_threads: int = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.watch_mode = watch_mode
        self.scan_path = path or "."
        self.watch_interval = interval
        self.threshold_bytes = threshold_bytes
        self.webhook = webhook
        self.notify_desktop = notify_desktop
        self.scan_threads = scan_threads
        self.last_size = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="top-panel"):
            yield PartitionPanel(id="partitions-box", classes="box accent-cyan")
            yield PredictionPanel(id="prediction-box", classes="box accent-blue")
            yield AnomalyPanel(id="anomaly-box", classes="box accent-violet")

        with Vertical(id="middle-panel"):
            yield DataTable(id="consumers-table")
            yield LoadingIndicator(id="scan-spinner")

        with Horizontal(id="bottom-panel"):
            yield ProblemsPanel(id="problems-box", classes="box accent-amber")
            yield PrescriptionsPanel(id="prescriptions-box", classes="box accent-green")
            yield ActiveWritersPanel(
                id="active-writers-box", classes="box accent-purple"
            )

        yield Footer()

    def on_mount(self) -> None:
        self.title = "dxcli"
        self.sub_title = "The Disk Doctor"

        self.query_one("#scan-spinner").display = False
        table = self.query_one("#consumers-table", DataTable)
        table.zebra_stripes = True
        table.cursor_type = "row"
        table.border_title = "TOP CONSUMERS"
        table.add_columns("Path", "Size", "Trend", "Process")

        if self.watch_mode:
            self.set_interval(self.watch_interval, self.action_diagnose)
            self.action_diagnose()

        self.action_refresh()

    def action_refresh(self) -> None:
        try:
            parts = provider.get_partitions()
            self.query_one(PartitionPanel).partitions = parts
        except Exception:
            pass

    def action_diagnose(self) -> None:
        if not self.is_scanning:
            self.run_scan()

    @work(exclusive=True, thread=True)
    def run_scan(self) -> None:
        self.is_scanning = True
        self.call_from_thread(self._show_spinner, True)

        try:
            from ..engine import run_diagnosis

            if hasattr(self, "scan_path") and self.scan_path:
                path = os.path.abspath(self.scan_path)
            else:
                parts = provider.get_partitions()
                if not parts:
                    return
                path = parts[0].mountpoint

            snap = run_diagnosis(
                path,
                scan_threads=getattr(self, "scan_threads", None),
                include_processes=True,
            )

            history_data = {t["path"]: t.get("history", []) for t in snap.trends}

            # Watch mode alerting logic
            current_size = sum(d.size_bytes for d in snap.top_dirs)
            if (
                self.watch_mode
                and self.last_size is not None
                and self.threshold_bytes > 0
            ):
                delta = current_size - self.last_size
                if delta > self.threshold_bytes:
                    if self.webhook:
                        from ..outputs.notifier import send_webhook

                        payload = {
                            "text": f"dxcli alert: Path '{path}' grew by {format_bytes(delta)} in {self.watch_interval}s.",
                            "path": path,
                            "delta_bytes": delta,
                        }
                        send_webhook(self.webhook, payload)
                    if self.notify_desktop:
                        from ..outputs.notifier import send_desktop_notification

                        send_desktop_notification(
                            "dxcli Disk Alert",
                            f"Path '{path}' grew by {format_bytes(delta)}.",
                        )
            self.last_size = current_size

            # Update UI from thread
            self.call_from_thread(
                self.update_results,
                snap.top_dirs,
                snap.trends,
                snap.logs,
                snap.stale_files,
                snap.prediction,
                snap.prescriptions,
                history_data,
                snap.anomalies,
                snap.active_writers,
            )

        except Exception as e:
            self.call_from_thread(self.notify, f"Scan failed: {e}", severity="error")
        finally:
            self.is_scanning = False
            self.call_from_thread(self._show_spinner, False)

    def _show_spinner(self, show: bool) -> None:
        self.query_one("#scan-spinner").display = show

    def update_results(
        self,
        top_dirs,
        correlated_trends,
        logs,
        stales,
        pred,
        prescs,
        history_data,
        anomalies,
        active_writers,
    ) -> None:
        # Update DataTable
        table = self.query_one("#consumers-table", DataTable)
        table.clear()

        # Update Anomalies
        if anomalies:
            self.query_one(AnomalyPanel).anomaly_text = "\n".join(
                [f"[{C_RED}]▲ {a}[/]" for a in anomalies]
            )
        else:
            self.query_one(AnomalyPanel).anomaly_text = (
                f"[{C_GREEN}]● Sentinel: Systems Nominal[/]"
            )

        # Map correlation and history
        trend_info = {t["path"]: t for t in correlated_trends}

        is_sr = getattr(self, "screen_reader", False) or (
            getattr(self, "app", None) and getattr(self.app, "screen_reader", False)
        )

        for d in top_dirs[:15]:
            info = trend_info.get(d.path, {})
            trend_str = info.get("trend", "Stable")

            # Process attribution
            culprit = info.get("culprit")
            proc_str = f"{culprit.name} ({culprit.pid})" if culprit else "—"

            if is_sr:
                # Plain text for screen readers.
                table.add_row(d.path, format_bytes(d.size_bytes), trend_str, proc_str)
                continue

            # Colour-coded, glyph-led cells.
            glyph, tcolor = _trend_glyph(trend_str)
            spark = sparkline_str(history_data.get(d.path, []))
            trend_cell = Text(f"{glyph} ", style=tcolor)
            trend_cell.append(spark if spark != "—" else trend_str, style=tcolor)

            size_cell = Text(format_bytes(d.size_bytes), style=f"bold {C_CYAN}")
            proc_cell = Text(proc_str, style=C_AMBER if culprit else C_MUTED)
            path_cell = Text(d.path, style="#C9D1D9")

            table.add_row(path_cell, size_cell, trend_cell, proc_cell)

        # Update Prediction — colour the headline by urgency.
        pp = self.query_one(PredictionPanel)
        if pred and pred.days_until_full is not None:
            growth = format_bytes(pred.daily_growth_bytes)
            if pred.days_until_full > 365:
                pp.prediction_text = (
                    f"[{C_GREEN} bold]◆ Stable (>1 year)[/]\n"
                    f"[{C_MUTED}]Growth {growth}/day[/]"
                )
            elif (
                pred.days_until_full_low is not None
                and pred.days_until_full_high is not None
            ):
                low = int(round(pred.days_until_full_low))
                high = int(round(pred.days_until_full_high))
                c = _urgency_color(low)
                if high > 365:
                    pp.prediction_text = (
                        f"[{c} bold]◆ Full in ≥ {low} days[/]\n"
                        f"[{C_MUTED}]Growth {growth}/day[/]"
                    )
                else:
                    pp.prediction_text = (
                        f"[{c} bold]◆ Full in {low}–{high} days[/]\n"
                        f"[{C_MUTED}]Growth {growth}/day[/]"
                    )
            else:
                c = _urgency_color(pred.days_until_full)
                pp.prediction_text = (
                    f"[{c} bold]◆ Full in {pred.days_until_full:.1f} days[/]\n"
                    f"[{C_MUTED}]Growth {growth}/day[/]"
                )
        elif pred and pred.hint == "high variance":
            pp.prediction_text = (
                f"[{C_AMBER} bold]◆ Unpredictable[/]\n"
                f"[{C_MUTED}]{format_bytes(pred.daily_growth_bytes)}/day (high variance)[/]"
            )
        else:
            pp.prediction_text = f"[{C_MUTED}]◆ Full in: N/A (Static)[/]"

        # Update Problems
        pb = self.query_one(ProblemsPanel)
        prob_count = len(logs) + len(stales)
        if prob_count > 0:
            pb.problems_text = (
                f"[{C_AMBER}]▲ {len(logs)} unrotated logs[/]\n"
                f"[{C_AMBER}]▲ {len(stales)} stale files[/]"
            )
        else:
            pb.problems_text = f"[{C_GREEN}]● No issues found[/]"

        # Update Prescriptions
        pr = self.query_one(PrescriptionsPanel)
        if prescs:
            savings = sum(p.size_savings_bytes for p in prescs)
            lines = [f"[{C_GREEN} bold]↓ Reclaim {format_bytes(savings)}[/]"]
            for i, p in enumerate(prescs[:3], 1):
                lines.append(f"[{C_MUTED}]{i}.[/] {p.name}")
            pr.prescriptions_text = "\n".join(lines)
        else:
            pr.prescriptions_text = f"[{C_MUTED}]No prescriptions available[/]"

        # Update Active Writers
        aw = self.query_one(ActiveWritersPanel)
        if active_writers:
            lines = []
            for w in active_writers[:3]:
                rate = format_bytes(int(w["throughput_bps"]))
                lines.append(
                    f"[{C_TEXT}]{w['name']}[/] "
                    f"[{C_MUTED}](PID {w['pid']})[/] "
                    f"[{C_PURPLE} bold]{rate}/s[/]"
                )
            aw.writers_text = "\n".join(lines)
        else:
            aw.writers_text = f"[{C_MUTED}]No active writers detected[/]"


if __name__ == "__main__":
    app = DxApp()
    app.run()
