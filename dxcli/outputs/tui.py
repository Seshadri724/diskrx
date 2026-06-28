from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Static, Label, LoadingIndicator
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual import work

from ..platform import provider
from ..store.database import Database
from ..store.models import Partition
from ..collectors.dir_tree import DirectoryTreeCollector
from ..collectors.log_finder import LogFinderCollector
from ..collectors.stale_files import StaleFileCollector
from ..analyzers import DiskPredictor, RootCauseAnalyzer, PrescriptionEngine, CorrelationEngine, StatisticalAnomalyDetector
from ..outputs.cli_report import format_bytes

import os


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
        yield Label("Partitions", classes="header-text")
        self.display_label = Label("Loading...")
        yield self.display_label

    def watch_partitions(self, parts: list[Partition]) -> None:
        out_str = ""
        for p in parts:
            width = 20
            filled = int((p.usage_percent / 100) * width)
            bar = ("█" * filled) + ("░" * (width - filled))
            out_str += f"{p.mountpoint:<6} {bar} {p.usage_percent:5.1f}%\n"
        self.display_label.update(out_str if out_str else "No partitions found.")

class PredictionPanel(Static):
    prediction_text = reactive("Run scan to calculate...")

    def compose(self) -> ComposeResult:
        yield Label("Prediction", classes="header-text")
        self.display_label = Label(self.prediction_text)
        yield self.display_label

    def watch_prediction_text(self, text: str) -> None:
        if hasattr(self, "display_label"):
            self.display_label.update(text)

class ProblemsPanel(Static):
    problems_text = reactive("[*] Waiting for deep scan...")

    def compose(self) -> ComposeResult:
        yield Label("Issues", classes="header-text")
        self.display_label = Label(self.problems_text)
        yield self.display_label

    def watch_problems_text(self, text: str) -> None:
        if hasattr(self, "display_label"):
            self.display_label.update(text)

class PrescriptionsPanel(Static):
    prescriptions_text = reactive("Press [d] to scan...")

    def compose(self) -> ComposeResult:
        yield Label("Prescriptions", classes="header-text")
        self.display_label = Label(self.prescriptions_text)
        yield self.display_label

    def watch_prescriptions_text(self, text: str) -> None:
        if hasattr(self, "display_label"):
            self.display_label.update(text)

class AnomalyPanel(Static):
    anomaly_text = reactive("[OK] Sentinel: Systems Nominal")

    def compose(self) -> ComposeResult:
        yield Label("Sentinel Analysis", classes="header-text")
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
        yield Label("Active Writers", classes="header-text")
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
    
    def __init__(self, watch_mode: bool = False, path: str = None, interval: float = 300.0, threshold_bytes: int = 0, webhook: str = None, notify_desktop: bool = False, scan_threads: int = None, **kwargs):
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
        yield Header(name="dxcli — The Disk Doctor")
        
        with Horizontal(id="top-panel"):
            yield PartitionPanel(id="partitions-box", classes="box")
            yield PredictionPanel(id="prediction-box", classes="box")
            yield AnomalyPanel(id="anomaly-box", classes="box")
            
        with Vertical(id="middle-panel"):
            yield DataTable(id="consumers-table")
            yield LoadingIndicator(id="scan-spinner")
            
        with Horizontal(id="bottom-panel"):
            yield ProblemsPanel(id="problems-box", classes="box")
            yield PrescriptionsPanel(id="prescriptions-box", classes="box")
            yield ActiveWritersPanel(id="active-writers-box", classes="box")
            
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#scan-spinner").display = False
        table = self.query_one("#consumers-table", DataTable)
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
            # 1. Get primary partition & path
            if hasattr(self, "scan_path") and self.scan_path:
                path = os.path.abspath(self.scan_path)
            else:
                parts = provider.get_partitions()
                if not parts:
                    return
                path = parts[0].mountpoint
            
            primary = provider.get_partition_for_path(path)
            if not primary:
                return
            
            # 2. Run collectors
            dir_collector = DirectoryTreeCollector(max_threads=self.scan_threads if hasattr(self, "scan_threads") else None)
            top_dirs = dir_collector.scan(path)
            
            log_collector = LogFinderCollector()
            logs = log_collector.scan([path])
            
            stale_collector = StaleFileCollector()
            stales = stale_collector.scan([path])
            
            # 3. Save snapshot for history (single db instance)
            db = Database()
            db.record_snapshot(primary, top_dirs)
            
            # 4. Analyze
            rca = RootCauseAnalyzer(db)
            trends = rca.attribute_cause(top_dirs)
            
            predictor = DiskPredictor(db)
            pred = predictor.predict_full_date(primary)
            
            engine = PrescriptionEngine()
            prescs = engine.synthesize(logs, stales, path)
            
            # 5. Correlate with Processes (single cached scan)
            correlator = CorrelationEngine()
            correlated_trends = correlator.correlate(trends)
            
            # 6. Get history for sparkline strings
            history_data = {}
            for d in top_dirs[:15]:
                h = db.get_dir_history(d.path, limit=20)
                history_data[d.path] = [entry['size_bytes'] for entry in h]
            
            # 7. Detect Anomalies
            detector = StatisticalAnomalyDetector(db)
            anomalies = []
            for d in top_dirs[:5]:
                res = detector.check_for_anomalies(d.path)
                if res:
                    anomalies.append(res)
            
            # 8. Active Writers Throughput Detection
            from ..collectors.process_mapper import ProcessMapper
            mapper = ProcessMapper()
            active_writers = mapper.get_active_writers(path, interval=0.5)

            # Watch mode alerting logic
            current_size = sum(d.size_bytes for d in top_dirs)
            if self.watch_mode and self.last_size is not None and self.threshold_bytes > 0:
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

            db.close()
            
            # 9. Update UI from thread
            self.call_from_thread(
                self.update_results, top_dirs, correlated_trends,
                logs, stales, pred, prescs, history_data, anomalies, active_writers
            )
            
        except Exception as e:
            self.call_from_thread(self.notify, f"Scan failed: {e}", severity="error")
        finally:
            self.is_scanning = False
            self.call_from_thread(self._show_spinner, False)

    def _show_spinner(self, show: bool) -> None:
        self.query_one("#scan-spinner").display = show

    def update_results(self, top_dirs, correlated_trends, logs, stales, pred, prescs, history_data, anomalies, active_writers) -> None:
        # Update DataTable
        table = self.query_one("#consumers-table", DataTable)
        table.clear()
        
        # Update Anomalies
        if anomalies:
            self.query_one(AnomalyPanel).anomaly_text = "\n".join([f"[!] {a}" for a in anomalies])
        else:
            self.query_one(AnomalyPanel).anomaly_text = "[OK] Sentinel: Systems Nominal"
        
        # Map correlation and history
        trend_info = {t['path']: t for t in correlated_trends}
        
        for d in top_dirs[:15]:
            info = trend_info.get(d.path, {})
            trend_str = info.get('trend', 'Stable')
            
            # Process attribution
            culprit = info.get('culprit')
            proc_str = f"{culprit.name} ({culprit.pid})" if culprit else "-"
            
            # String-based sparkline (no widget crash)
            hist = history_data.get(d.path, [])
            spark = sparkline_str(hist)
            trend_display = f"{trend_str} {spark}" if spark != "—" else trend_str
                
            table.add_row(d.path, format_bytes(d.size_bytes), trend_display, proc_str)
            
        # Update Prediction - now showing confidence bands and checking for >365 days / stable
        if pred and pred.days_until_full is not None:
            if pred.days_until_full > 365:
                self.query_one(PredictionPanel).prediction_text = (
                    f"[~] Full in: Stable (>1 year)\n"
                    f"Growth: {format_bytes(pred.daily_growth_bytes)}/day"
                )
            elif pred.days_until_full_low is not None and pred.days_until_full_high is not None:
                low = int(round(pred.days_until_full_low))
                high = int(round(pred.days_until_full_high))
                if high > 365:
                    self.query_one(PredictionPanel).prediction_text = (
                        f"[~] Full in >= {low} days\n"
                        f"Growth: {format_bytes(pred.daily_growth_bytes)}/day"
                    )
                else:
                    self.query_one(PredictionPanel).prediction_text = (
                        f"[~] Full in {low}–{high} days\n"
                        f"Growth: {format_bytes(pred.daily_growth_bytes)}/day"
                    )
            else:
                self.query_one(PredictionPanel).prediction_text = (
                    f"[~] Full in {pred.days_until_full:.1f} days\n"
                    f"Growth: {format_bytes(pred.daily_growth_bytes)}/day"
                )
        elif pred and pred.hint == "high variance":
            self.query_one(PredictionPanel).prediction_text = (
                f"[~] Full in: Unpredictable\n"
                f"Growth: {format_bytes(pred.daily_growth_bytes)}/day (high variance)"
            )
        else:
            self.query_one(PredictionPanel).prediction_text = "[~] Full in: N/A (Static)"
            
        # Update Problems
        prob_count = len(logs) + len(stales)
        if prob_count > 0:
            prob_str = f"[!] Found {len(logs)} unrotated logs\n[*] Found {len(stales)} stale files"
            self.query_one(ProblemsPanel).problems_text = prob_str
        else:
            self.query_one(ProblemsPanel).problems_text = "[OK] No issues found."
            
        # Update Prescriptions
        if prescs:
            savings = sum(p.size_savings_bytes for p in prescs)
            presc_str = f"Estimated savings: {format_bytes(savings)}\n"
            for i, p in enumerate(prescs[:3], 1):
                presc_str += f"[{i}] {p.name}\n"
            self.query_one(PrescriptionsPanel).prescriptions_text = presc_str
        else:
            self.query_one(PrescriptionsPanel).prescriptions_text = "No prescriptions available."

        # Update Active Writers
        if active_writers:
            writer_str = ""
            for w in active_writers[:3]:
                writer_str += f"{w['name']} (PID {w['pid']}): {format_bytes(int(w['throughput_bps']))}/s\n"
            self.query_one(ActiveWritersPanel).writers_text = writer_str.strip()
        else:
            self.query_one(ActiveWritersPanel).writers_text = "No active writers detected."

if __name__ == '__main__':
    app = DxApp()
    app.run()

