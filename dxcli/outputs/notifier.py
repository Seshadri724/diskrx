import urllib.request
import urllib.error
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def send_webhook(url: str, payload: Dict[str, Any]) -> bool:
    """
    Sends a generic JSON webhook payload (e.g. to Slack, Discord, PagerDuty).
    Uses standard library urllib to avoid adding dependencies.
    """
    if not url:
        return False
        
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
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status in (200, 201, 202, 204)
    except urllib.error.URLError as e:
        logger.error(f"Webhook delivery failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Webhook delivery error: {e}")
        return False
