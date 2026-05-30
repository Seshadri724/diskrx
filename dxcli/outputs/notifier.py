import json
import logging
import ipaddress
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


import http.client
import ssl

class PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port=None, pinned_ip=None, **kwargs):
        self.pinned_ip = pinned_ip
        super().__init__(host, port, **kwargs)

    def connect(self):
        self.sock = socket.create_connection(
            (self.pinned_ip, self.port),
            self.timeout,
            self.source_address
        )

class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port=None, pinned_ip=None, **kwargs):
        self.pinned_ip = pinned_ip
        super().__init__(host, port, **kwargs)

    def connect(self):
        self.sock = socket.create_connection(
            (self.pinned_ip, self.port),
            self.timeout,
            self.source_address
        )
        self.sock = self._context.wrap_socket(
            self.sock,
            server_hostname=self.host
        )

class PinnedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, pinned_ip):
        self.pinned_ip = pinned_ip
        super().__init__()

    def http_open(self, req):
        def build_connection(host, **kwargs):
            return PinnedHTTPConnection(host, pinned_ip=self.pinned_ip, **kwargs)
        return self.do_open(build_connection, req)

class PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pinned_ip, context=None):
        self.pinned_ip = pinned_ip
        super().__init__(context=context)

    def https_open(self, req):
        def build_connection(host, **kwargs):
            return PinnedHTTPSConnection(host, pinned_ip=self.pinned_ip, **kwargs)
        return self.do_open(build_connection, req,
            context=self._context, check_hostname=self._check_hostname)

class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"Redirects are disabled: redirection to {newurl} rejected", headers, fp)


def validate_webhook_destination(url: str, allow_private: bool = False) -> Tuple[bool, str, Optional[str]]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"Invalid webhook scheme '{parsed.scheme}'. Only http and https are allowed.", None
    if not parsed.hostname:
        return False, "Invalid webhook URL: host is required.", None

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return False, f"Hostname resolution failed: {e}", None

    resolved_ip = None
    for result in addresses:
        address = result[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False, f"Invalid resolved IP address '{address}'", None

        if not allow_private and (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, "Webhook host resolves to a private, loopback, link-local, or reserved address.", None

        if not resolved_ip:
            resolved_ip = address

    if not resolved_ip:
        return False, "No IP address found for host.", None

    return True, "", resolved_ip


def send_webhook(url: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Sends a generic JSON webhook payload (e.g. to Slack, Discord, PagerDuty).
    Uses standard library urllib to avoid adding dependencies.
    Returns (success, error_message).
    """
    if not url:
        return False, "No URL provided"

    is_valid, error, pinned_ip = validate_webhook_destination(url)
    if not is_valid:
        return False, error
        
    # Standard generic fallback if complex layout isn't needed
    if "text" not in payload and "message" in payload:
        payload["text"] = payload["message"]
        
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url, 
        data=data, 
        headers={'Content-Type': 'application/json', 'User-Agent': 'dxcli/1.0'},
        method='POST'
    )
    
    context = ssl.create_default_context()
    handlers = [
        NoRedirectHandler(),
        PinnedHTTPHandler(pinned_ip),
        PinnedHTTPSHandler(pinned_ip, context=context)
    ]
    opener = urllib.request.build_opener(*handlers)
    
    try:
        # Production Hardening: 5 second timeout to prevent blocking the watch loop
        with opener.open(req, timeout=5.0) as response:
            if response.status in (200, 201, 202, 204):
                return True, ""
            return False, f"HTTP Status {response.status}"
    except urllib.error.URLError as e:
        msg = f"Webhook delivery failed: {e.reason}"
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"Webhook delivery error: {str(e)}"
        logger.error(msg)
        return False, msg

def send_desktop_notification(title: str, message: str):
    """
    Sends a native desktop notification without external dependencies.
    """
    try:
        if sys.platform == "win32":
            import os
            os.environ["DX_TITLE"] = str(title)
            os.environ["DX_MESSAGE"] = str(message)
            try:
                ps_script = """
                Add-Type -AssemblyName System.Windows.Forms
                $notification = New-Object System.Windows.Forms.NotifyIcon
                $notification.Icon = [System.Drawing.SystemIcons]::Information
                $notification.BalloonTipTitle = $env:DX_TITLE
                $notification.BalloonTipText = $env:DX_MESSAGE
                $notification.Visible = $true
                $notification.ShowBalloonTip(5000)
                """
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, check=False)
            finally:
                os.environ.pop("DX_TITLE", None)
                os.environ.pop("DX_MESSAGE", None)
        elif sys.platform == "darwin":
            script = 'on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run'
            subprocess.run(["osascript", "-e", script, str(title), str(message)], check=False)
        else:
            # Linux notification (fallback to notify-send)
            subprocess.run(["notify-send", str(title), str(message)], check=False)
    except Exception as e:
        logger.debug(f"Desktop notification failed: {e}")
