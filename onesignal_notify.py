"""
Send push notifications via OneSignal REST API.

Set ONESIGNAL_REST_API_KEY in the environment (from OneSignal Dashboard -> Keys & IDs).
App ID is the same as in the frontend OneSignal.init().
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

ONESIGNAL_APP_ID = "677b2f11-dd7c-4326-88b9-02bf6f31c5f9"
ONESIGNAL_API_URL = "https://api.onesignal.com/notifications"


def send_push(
    message: str,
    heading: Optional[str] = None,
    segment: str = "Subscribed Users") -> bool:
    """
    Send a push notification to the target segment (default: Subscribed Users).

    Returns True if the request was accepted by OneSignal, False if skipped (no API key)
    or on error (logged).
    """
    apiKey = os.environ.get("ONESIGNAL_REST_API_KEY")
    if not apiKey:
        logger.debug("ONESIGNAL_REST_API_KEY not set; skipping push")
        return False

    payload = {
        "app_id": ONESIGNAL_APP_ID,
        "target_channel": "push",
        "included_segments": [segment],
        "contents": {"en": message},
    }
    if heading:
        payload["headings"] = {"en": heading}

    try:
        import requests
        resp = requests.post(
            ONESIGNAL_API_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Key {apiKey}",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        logger.warning("OneSignal push failed: %s %s", resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.warning("OneSignal push error: %s", e)
        return False
