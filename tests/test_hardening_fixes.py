import pytest
from unittest.mock import patch, MagicMock
import urllib.request
import urllib.error
import socket
import os
from dxcli.outputs.notifier import validate_webhook_destination, send_webhook

def test_validate_webhook_destination_returns_ip():
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
        ]
        is_valid, err, ip = validate_webhook_destination("https://example.com/hook")
        assert is_valid is True
        assert err == ""
        assert ip == "93.184.216.34"

def test_validate_webhook_destination_rejects_private_ip():
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))
        ]
        is_valid, err, ip = validate_webhook_destination("https://example.com/hook")
        assert is_valid is False
        assert "private" in err or "loopback" in err

def test_no_redirect_handler():
    from dxcli.outputs.notifier import NoRedirectHandler
    handler = NoRedirectHandler()
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        handler.redirect_request(MagicMock(full_url="http://foo"), MagicMock(), 302, "Found", {}, "http://bar")
    assert "Redirects are disabled" in str(exc_info.value)

def test_send_desktop_notification_win32_uses_env(monkeypatch):
    ps_commands = []
    
    def mock_run(args, **kwargs):
        ps_commands.append((args, os.environ.get("DX_TITLE"), os.environ.get("DX_MESSAGE")))
        return MagicMock()
        
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr("subprocess.run", mock_run)
    
    from dxcli.outputs.notifier import send_desktop_notification
    send_desktop_notification("Test Title", "Test Message")
    
    assert len(ps_commands) == 1
    args, title, msg = ps_commands[0]
    assert args[0] == "powershell"
    assert title == "Test Title"
    assert msg == "Test Message"
    
    assert "DX_TITLE" not in os.environ
    assert "DX_MESSAGE" not in os.environ
