from http.server import BaseHTTPRequestHandler, HTTPServer
import time
from ..store.database import Database
from ..platform import provider

class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/metrics':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.end_headers()
            
            output = []
            db = Database()
            
            # 1. Global Partition Metrics
            try:
                parts = provider.get_partitions()
                for p in parts:
                    safe_mount = p.mountpoint.replace('\\', '/').replace(':', '')
                    output.append(f'dx_partition_usage_percent{{mountpoint="{safe_mount}"}} {p.usage_percent}')
                    output.append(f'dx_partition_used_bytes{{mountpoint="{safe_mount}"}} {p.used_bytes}')
                    output.append(f'dx_partition_total_bytes{{mountpoint="{safe_mount}"}} {p.total_bytes}')
            except Exception:
                pass
                
            # 2. Add some status metrics (Phase 4 heartbeats)
            output.append(f'dx_sentinel_active 1')
            output.append(f'dx_last_scrape_timestamp {time.time()}')
            
            self.wfile.write("\n".join(output).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence logs to keep CLI clean
        return

def start_metrics_server(port: int, bind: str = '127.0.0.1'):
    server = HTTPServer((bind, port), MetricsHandler)
    server.serve_forever()
