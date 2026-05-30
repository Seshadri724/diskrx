import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer

from ..store.database import Database
from ..platform import provider

logger = logging.getLogger(__name__)


def prometheus_label_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class MetricsHandler(BaseHTTPRequestHandler):
    """Serves Prometheus-format metrics at /metrics."""

    def do_GET(self) -> None:
        auth_token = getattr(self.server, "auth_token", None)
        if auth_token:
            auth_header = self.headers.get("Authorization")
            if not auth_header or not auth_header.lower().startswith("bearer "):
                self.send_response(401)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Unauthorized: invalid or missing bearer token")
                return
            import hmac
            token_part = auth_header[7:]
            if not hmac.compare_digest(token_part.encode("utf-8"), auth_token.encode("utf-8")):
                self.send_response(401)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Unauthorized: invalid or missing bearer token")
                return

        if self.path == "/metrics":
            self._handle_metrics()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_metrics(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()

        output = []
        db = Database()
        parts = []

        try:
            # 1. Global partition metrics
            try:
                parts = provider.get_partitions()
                for p in parts:
                    safe_mount = prometheus_label_value(p.mountpoint.replace("\\", "/").replace(":", ""))
                    output.append(f'dx_partition_usage_percent{{mountpoint="{safe_mount}"}} {p.usage_percent}')
                    output.append(f'dx_partition_used_bytes{{mountpoint="{safe_mount}"}} {p.used_bytes}')
                    output.append(f'dx_partition_total_bytes{{mountpoint="{safe_mount}"}} {p.total_bytes}')
            except Exception as e:
                logger.warning("Partition metrics collection failed: %s", e)

            # 2. Heartbeat metrics
            output.append("dx_sentinel_active 1")
            output.append(f"dx_last_scrape_timestamp {time.time()}")

            # 3. Growth / prediction metrics
            try:
                from ..analyzers.predictor import DiskPredictor
                predictor = DiskPredictor(db)
                for p in parts:
                    safe_mount = prometheus_label_value(p.mountpoint.replace("\\", "/").replace(":", ""))
                    pred = predictor.predict_full_date(p)
                    if pred:
                        output.append(
                            f'dx_partition_daily_growth_bytes{{mountpoint="{safe_mount}"}} {pred.daily_growth_bytes}'
                        )
                        days = pred.days_until_full if pred.days_until_full is not None else -1
                        output.append(
                            f'dx_partition_days_to_full{{mountpoint="{safe_mount}"}} {days}'
                        )
            except Exception as e:
                logger.warning("Prediction metrics collection failed: %s", e)

        finally:
            db.close()

        try:
            self.wfile.write("\n".join(output).encode("utf-8"))
        except Exception as e:
            logger.error("Failed to write metrics response: %s", e)

    def log_message(self, format: str, *args) -> None:
        # Route HTTP access logs to the Python logger instead of stderr
        logger.debug("metrics: " + format, *args)


class HardenedThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def start_metrics_server(port: int, bind: str = "127.0.0.1", auth_token: str = None) -> None:
    """Start the blocking HTTP metrics server.

    Raises OSError if the bind address/port is already in use, so the caller
    (a daemon thread in serve) can surface the failure instead of silently dying.
    """
    server = create_metrics_server(port, bind, auth_token)
    logger.info("Metrics server started on %s:%d", bind, port)
    server.serve_forever()


def create_metrics_server(port: int, bind: str = "127.0.0.1", auth_token: str = None) -> HardenedThreadingHTTPServer:
    """Create a metrics server without starting it, surfacing bind failures to callers."""
    server = HardenedThreadingHTTPServer((bind, port), MetricsHandler)
    server.auth_token = auth_token
    server.timeout = 5
    return server
