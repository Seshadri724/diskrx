import os
import time
from html import escape
from typing import List
from ..store.models import Partition, DirNode, Prescription, UnrotatedLog, StaleFile
from .cli_report import format_bytes

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>dxcli - Disk Intelligence Report</title>
    <style>
        :root {{
            --bg: #0f172a;
            --surface: #1e293b;
            --text: #f8fafc;
            --text-muted: #cbd5e1;
            --primary: #60a5fa;
            --danger: #f87171;
            --success: #4ade80;
            --warning: #fbbf24;
            --border: #334155;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            line-height: 1.6;
            margin: 0;
            padding: 2rem;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
        }}
        .header {{
            border-bottom: 1px solid var(--border);
            padding-bottom: 1rem;
            margin-bottom: 2rem;
        }}
        .header h1 {{
            margin: 0;
            color: var(--primary);
            font-size: 1.5rem;
        }}
        .header .path {{
            color: var(--text-muted);
            font-family: monospace;
            margin-top: 0.5rem;
        }}
        .card {{
            background-color: var(--surface);
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            border: 1px solid var(--border);
        }}
        .action-required {{
            border-color: var(--danger);
            border-left: 4px solid var(--danger);
        }}
        h2 {{
            margin-top: 0;
            font-size: 1.25rem;
            color: var(--text);
            border-bottom: 1px solid var(--border);
            padding-bottom: 0.5rem;
        }}
        .stat-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 1rem;
        }}
        .stat {{
            background-color: rgba(0,0,0,0.2);
            padding: 1rem;
            border-radius: 6px;
        }}
        .stat-label {{
            font-size: 0.875rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .stat-value {{
            font-size: 1.5rem;
            font-weight: bold;
            margin-top: 0.25rem;
        }}
        .danger-text {{ color: var(--danger); }}
        .success-text {{ color: var(--success); }}
        .warning-text {{ color: var(--warning); }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-family: monospace;
        }}
        th, td {{
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        th {{
            color: var(--text-muted);
            font-weight: 600;
        }}
        .text-right {{ text-align: right; }}
        .mono {{ font-family: monospace; }}
        .code-block {{
            background: #000;
            padding: 1rem;
            border-radius: 4px;
            font-family: monospace;
            color: #fff;
            margin-top: 1rem;
        }}
    </style>
</head>
<body>
    <main class="container" role="main">
        <header class="header">
            <h1>dxcli Disk Intelligence Report</h1>
            <div class="path">{path}</div>
            <div style="font-size: 0.875rem; color: var(--text-muted); margin-top: 0.5rem;">
                Generated on {timestamp}
            </div>
        </header>

        {action_section}

        <section class="card" aria-label="Partition Status">
            <h2>Partition Status</h2>
            <div class="stat-grid">
                <div class="stat">
                    <div class="stat-label">Mountpoint</div>
                    <div class="stat-value">{mountpoint}</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Usage</div>
                    <div class="stat-value">{usage_percent}%</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Forecast</div>
                    <div class="stat-value {forecast_class}">{forecast}</div>
                </div>
            </div>
        </section>

        {culprit_section}

        <section class="card" aria-label="Top Storage Consumers">
            <h2>Top Storage Consumers</h2>
            <table>
                <caption>Top storage-consuming directories sorted by size</caption>
                <thead>
                    <tr>
                        <th scope="col">Path</th>
                        <th scope="col" class="text-right">Size</th>
                        <th scope="col" class="text-right">Growth/Day</th>
                    </tr>
                </thead>
                <tbody>
                    {consumers_rows}
                </tbody>
            </table>
        </section>
        
        <footer style="text-align: center; color: var(--text-muted); font-size: 0.875rem; margin-top: 2rem;">
            Generated by <a href="https://github.com/Seshadri724/dxcli" style="color: var(--primary);" aria-label="dxcli open source repository on GitHub">dxcli</a>
        </footer>
    </main>
</body>
</html>
"""

def generate_html_report(out_path: str, path: str, partition: Partition, top_dirs: List[DirNode], 
                         logs: List[UnrotatedLog], stales: List[StaleFile], trends: List[dict] = None, 
                         prescriptions: List[Prescription] = None, prediction=None):
    
    trend_info = {t['path']: t for t in trends} if trends else {}
    html_path = escape(os.path.abspath(path), quote=True)
    html_mountpoint = escape(partition.mountpoint, quote=True) if partition else "Unknown"

    # Action Section
    action_section = ""
    if prescriptions:
        p = prescriptions[0]
        total_savings = sum(pr.size_savings_bytes for pr in prescriptions)
        prescription_name = escape(p.name, quote=True)
        action_section = f"""
        <section class="card action-required" aria-label="Action Required">
            <h2 class="danger-text" style="border: none; padding: 0;">[!] ACTION REQUIRED</h2>
            <p><strong>Primary Fix:</strong> {prescription_name}</p>
            <p><strong>Potential Savings:</strong> {format_bytes(total_savings)}</p>
            <div class="code-block">dxcli heal</div>
        </section>
        """

    # Partition Forecast
    forecast = "Stable"
    forecast_class = "success-text"
    if prediction and prediction.days_until_full is not None:
        days = prediction.days_until_full
        if days < 7:
            forecast = f"Full in {days:.1f} days"
            forecast_class = "danger-text"
        else:
            forecast = f"Full in {days:.0f} days"
            forecast_class = "warning-text"

    # Culprit Section
    culprit_section = ""
    if trends and len(trends) > 0:
        fastest = max(trends, key=lambda t: t.get('velocity_per_day', 0))
        vel = fastest.get('velocity_per_day', 0)
        
        if vel > 1024 * 1024:
            culprit = fastest.get('culprit')
            proc_str = (
                f" (PID {escape(str(culprit.pid), quote=True)} - {escape(culprit.name, quote=True)})"
                if culprit
                else ""
            )
            culprit_path = escape(str(fastest.get('path', '')), quote=True)
            culprit_section = f"""
            <section class="card" aria-label="Primary Culprit">
                <h2>Primary Culprit</h2>
                <p class="mono">{culprit_path}</p>
                <p>Growing at <strong class="danger-text">{format_bytes(vel)}/day</strong>{proc_str}</p>
            </section>
            """

    # Consumer Rows
    consumers_rows = ""
    for d in top_dirs[:10]:
        info = trend_info.get(d.path, {})
        vel = info.get('velocity_per_day', 0)
        vel_str = f"{format_bytes(vel)}/day" if vel > 0 else "-"
        row_path = escape(d.path, quote=True)
        consumers_rows += f"""
        <tr>
            <td>{row_path}</td>
            <td class="text-right">{format_bytes(d.size_bytes)}</td>
            <td class="text-right">{vel_str}</td>
        </tr>
        """

    html = HTML_TEMPLATE.format(
        path=html_path,
        timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
        action_section=action_section,
        mountpoint=html_mountpoint,
        usage_percent=f"{partition.usage_percent:.1f}" if partition else "0",
        forecast=forecast,
        forecast_class=forecast_class,
        culprit_section=culprit_section,
        consumers_rows=consumers_rows
    )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
