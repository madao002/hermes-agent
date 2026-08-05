"""
Feishu/Lark message sender via direct HTTP API.
Replaces the lark-cli subprocess approach with direct requests to Feishu Open API.
This avoids the subprocess initialization issues seen in the Gateway's asyncio environment.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("feishu_lark_cli")

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

APP_ID = "cli_a9576d7eed7adccb"
APP_SECRET = "oYhQVur8pHQQ1fJPSBaWggMJvMZcuggk"
FEISHU_API_BASE = "https://open.larksuite.com/open-apis"

# Token cache with thread-safe access
_token_cache: Dict[str, Any] = {
    "token": None,
    "expires_at": 0.0,
}
_token_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# Token management
# ─────────────────────────────────────────────────────────────────────────────

def _get_tenant_token() -> Optional[str]:
    """Get a valid tenant access token, refreshing if necessary."""
    global _token_cache

    # Fast path: check without lock
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    with _token_lock:
        # Double-check after acquiring lock
        if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
            return _token_cache["token"]

        # Refresh token
        try:
            resp = requests.post(
                f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal",
                json={"app_id": APP_ID, "app_secret": APP_SECRET},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    _token_cache["token"] = data["tenant_access_token"]
                    # Feishu tokens expire in 2 hours, cache for 1.5 hours
                    _token_cache["expires_at"] = now + 5400
                    return _token_cache["token"]
                else:
                    logger.error("[FeishuLC] Token request failed: code=%s msg=%s", data.get("code"), data.get("msg"))
            else:
                logger.error("[FeishuLC] Token request HTTP %s: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.error("[FeishuLC] Token request exception: %s", e)

        return None


# ─────────────────────────────────────────────────────────────────────────────
# Core HTTP sender
# ─────────────────────────────────────────────────────────────────────────────

def _http_send(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    retry: bool = True,
) -> dict:
    """
    Make an authenticated HTTP request to Feishu API.

    Returns:
        {"ok": bool, "data": {...}, "error": {...}}  (lark-cli compatible format)
    """
    max_retries = 3 if retry else 1

    for attempt in range(max_retries):
        if attempt > 0:
            delay = 2 ** attempt
            logger.warning("[FeishuLC] Retry %d/%d after %ds", attempt, max_retries, delay)
            time.sleep(delay)

        token = _get_tenant_token()
        if not token:
            last_err = {"ok": False, "error": {"message": "Failed to obtain tenant access token"}}
            continue

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        url = f"{FEISHU_API_BASE}{path}"
        try:
            if method == "POST":
                resp = requests.post(url, headers=headers, json=body, params=params, timeout=30)
            elif method == "PATCH":
                resp = requests.patch(url, headers=headers, json=body, params=params, timeout=30)
            elif method == "GET":
                resp = requests.get(url, headers=headers, params=params, timeout=30)
            else:
                return {"ok": False, "error": {"message": f"Unsupported method: {method}"}}

            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return {"ok": True, "data": data.get("data", {})}
                else:
                    # Feishu API error
                    err_msg = data.get("msg", str(data))
                    err_code = data.get("code")
                    logger.error("[FeishuLC] API error %s: %s", err_code, err_msg)

                    # Non-retryable errors
                    if err_code in (230001, 99991401, 99991402, 99991403):
                        return {"ok": False, "error": {"message": err_msg, "code": err_code}}

                    last_err = {"ok": False, "error": {"message": err_msg, "code": err_code}}
                    # Retry on server errors (5xx, rate limit)
                    if err_code in (99991400,) or "rate limit" in err_msg.lower():
                        continue
                    continue
            elif resp.status_code == 401:
                # Token expired, force refresh
                with _token_lock:
                    _token_cache["token"] = None
                    _token_cache["expires_at"] = 0.0
                logger.warning("[FeishuLC] Token expired, refreshing...")
                last_err = {"ok": False, "error": {"message": "Token expired"}}
                continue
            else:
                logger.error("[FeishuLC] HTTP %s: %s", resp.status_code, resp.text[:200])
                last_err = {"ok": False, "error": {"message": f"HTTP {resp.status_code}"}}
                continue

        except requests.Timeout:
            logger.warning("[FeishuLC] Request timeout (attempt %d/%d)", attempt + 1, max_retries)
            last_err = {"ok": False, "error": {"message": "Request timeout"}}
            continue
        except Exception as e:
            logger.error("[FeishuLC] Request exception: %s", e)
            last_err = {"ok": False, "error": {"message": str(e)}}
            continue

    return last_err or {"ok": False, "error": {"message": "all retries failed"}}


# ─────────────────────────────────────────────────────────────────────────────
# Core send primitives
# ─────────────────────────────────────────────────────────────────────────────

def _detect_receive_id_type(chat_id: str) -> str:
    """Auto-detect receive_id_type based on chat_id prefix."""
    if chat_id.startswith(("ou_", "ob_", "popen_")):
        return "open_id"
    return "chat_id"


def cli_send_text(
    chat_id: str,
    text: str,
    *,
    reply_to: Optional[str] = None,
    thread_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> dict:
    """Send a plain text message via Feishu API."""
    content = json.dumps({"text": text}, ensure_ascii=False)
    receive_id_type = _detect_receive_id_type(chat_id)

    body = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": content,
    }
    if reply_to:
        body["reply_to"] = reply_to

    result = _http_send(
        "POST",
        f"/im/v1/messages?receive_id_type={receive_id_type}",
        body=body,
    )

    if result.get("ok"):
        data = result.get("data", {})
        return {"ok": True, "message_id": data.get("message_id"), "error": None}
    else:
        err = result.get("error", {})
        return {"ok": False, "message_id": None, "error": err.get("message", str(err))}


def cli_send_markdown(
    chat_id: str,
    markdown: str,
    *,
    reply_to: Optional[str] = None,
    thread_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> dict:
    """Send a markdown message via Feishu API (post type)."""
    content = json.dumps({"text": markdown}, ensure_ascii=False)
    receive_id_type = _detect_receive_id_type(chat_id)

    body = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": content,
    }
    if reply_to:
        body["reply_to"] = reply_to

    result = _http_send(
        "POST",
        f"/im/v1/messages?receive_id_type={receive_id_type}",
        body=body,
    )

    if result.get("ok"):
        data = result.get("data", {})
        return {"ok": True, "message_id": data.get("message_id"), "error": None}
    else:
        err = result.get("error", {})
        return {"ok": False, "message_id": None, "error": err.get("message", str(err))}


def cli_send_card(
    chat_id: str,
    card_json: str,
    *,
    reply_to: Optional[str] = None,
    thread_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> dict:
    """Send an interactive card via Feishu API."""
    receive_id_type = _detect_receive_id_type(chat_id)

    body = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": card_json,
    }
    if reply_to:
        body["reply_to"] = reply_to

    result = _http_send(
        "POST",
        f"/im/v1/messages?receive_id_type={receive_id_type}",
        body=body,
    )

    if result.get("ok"):
        data = result.get("data", {})
        return {"ok": True, "message_id": data.get("message_id"), "error": None}
    else:
        err = result.get("error", {})
        return {"ok": False, "message_id": None, "error": err.get("message", str(err))}


def cli_send_image(chat_id: str, image_path: str, **kwargs) -> dict:
    """Send a local image via Feishu API (multipart upload)."""
    path = Path(image_path).resolve()
    if not path.exists():
        return {"ok": False, "message_id": None, "error": f"file not found: {image_path}"}

    # Step 1: Upload image to get image_key
    try:
        token = _get_tenant_token()
        if not token:
            return {"ok": False, "message_id": None, "error": "Failed to obtain token"}

        with open(path, "rb") as f:
            files = {"image": (path.name, f, "image/png")}
            data = {"image_type": "message"}
            headers = {"Authorization": f"Bearer {token}"}
            resp = requests.post(
                f"{FEISHU_API_BASE}/im/v1/images",
                headers=headers,
                data=data,
                files=files,
                timeout=30,
            )

        if resp.status_code != 200:
            return {"ok": False, "message_id": None, "error": f"Image upload failed: {resp.status_code}"}

        result = resp.json()
        if result.get("code") != 0:
            return {"ok": False, "message_id": None, "error": f"Image upload error: {result.get('msg')}"}

        image_key = result["data"]["image_key"]
    except Exception as e:
        return {"ok": False, "message_id": None, "error": f"Image upload exception: {e}"}

    # Step 2: Send image message
    receive_id_type = _detect_receive_id_type(chat_id)
    body = {
        "receive_id": chat_id,
        "msg_type": "image",
        "content": json.dumps({"image_key": image_key}),
    }

    result = _http_send(
        "POST",
        f"/im/v1/messages?receive_id_type={receive_id_type}",
        body=body,
    )

    if result.get("ok"):
        data = result.get("data", {})
        return {"ok": True, "message_id": data.get("message_id"), "error": None}
    else:
        err = result.get("error", {})
        return {"ok": False, "message_id": None, "error": err.get("message", str(err))}


def cli_send_file(chat_id: str, file_path: str, **kwargs) -> dict:
    """Send a local file via Feishu API (multipart upload)."""
    path = Path(file_path).resolve()
    if not path.exists():
        return {"ok": False, "message_id": None, "error": f"file not found: {file_path}"}

    try:
        token = _get_tenant_token()
        if not token:
            return {"ok": False, "message_id": None, "error": "Failed to obtain token"}

        file_size = path.stat().st_size
        with open(path, "rb") as f:
            files = {"file": (path.name, f, "application/octet-stream")}
            data = {"file_name": path.name, "file_size": str(file_size), "file_type": "stream"}
            headers = {"Authorization": f"Bearer {token}"}
            resp = requests.post(
                f"{FEISHU_API_BASE}/im/v1/files",
                headers=headers,
                data=data,
                files=files,
                timeout=60,
            )

        if resp.status_code != 200:
            return {"ok": False, "message_id": None, "error": f"File upload failed: {resp.status_code}"}

        result = resp.json()
        if result.get("code") != 0:
            return {"ok": False, "message_id": None, "error": f"File upload error: {result.get('msg')}"}

        file_key = result["data"]["file_key"]

        # Step 2: Send file message
        receive_id_type = _detect_receive_id_type(chat_id)
        body = {
            "receive_id": chat_id,
            "msg_type": "file",
            "content": json.dumps({"file_key": file_key}),
        }

        result = _http_send(
            "POST",
            f"/im/v1/messages?receive_id_type={receive_id_type}",
            body=body,
        )

        if result.get("ok"):
            data = result.get("data", {})
            msg_id = data.get("message_id")

            caption = kwargs.get("caption")
            if caption:
                text_result = cli_send_text(chat_id, caption, reply_to=msg_id)
                return text_result
            return {"ok": True, "message_id": msg_id, "error": None}
        else:
            err = result.get("error", {})
            return {"ok": False, "message_id": None, "error": err.get("message", str(err))}

    except Exception as e:
        return {"ok": False, "message_id": None, "error": f"File send exception: {e}"}


def cli_send_audio(chat_id: str, audio_path: str, **kwargs) -> dict:
    """Send a local audio file via Feishu API."""
    # Audio uses same file upload flow
    return cli_send_file(chat_id, audio_path, **kwargs)


def cli_send_video(chat_id: str, video_path: str, **kwargs) -> dict:
    """Send a local video via Feishu API."""
    # Video uses same file upload flow
    return cli_send_file(chat_id, video_path, **kwargs)


def cli_edit_message(message_id: str, content: str, **kwargs) -> dict:
    """Edit an existing message via Feishu API."""
    content_json = json.dumps({"text": content}, ensure_ascii=False)

    result = _http_send(
        "PATCH",
        f"/im/v1/messages/{message_id}",
        body={"content": content_json, "msg_type": "text"},
        retry=False,
    )

    if result.get("ok"):
        return {"ok": True, "message_id": message_id, "error": None}
    else:
        err = result.get("error", {})
        return {"ok": False, "message_id": None, "error": err.get("message", str(err))}


# ─────────────────────────────────────────────────────────────────────────────
# Error classification helper
# ─────────────────────────────────────────────────────────────────────────────

def _is_network_error(error_val: Any) -> bool:
    """Return True if the error is retryable (network/server overload)."""
    if not error_val:
        return False
    error_str = str(error_val).lower()
    network_patterns = (
        "connection", "timeout", "refused", "reset", "unreachable",
        "temporary", "503", "502", "504", "429", "rate limit",
        "too many", "overload", "busy", "529",
    )
    non_retryable = ("230001", "99991401", "99991402", "99991403")
    for p in non_retryable:
        if p in error_str:
            return False
    return any(p in error_str for p in network_patterns)


# ─────────────────────────────────────────────────────────────────────────────
# SendResult dataclass helper
# ─────────────────────────────────────────────────────────────────────────────

def send_result_to_sendl_result(d: dict):
    """Convert our dict format to FeishuAdapter's SendResult dataclass."""
    from dataclasses import dataclass
    @dataclass
    class _SendResult:
        success: bool
        message_id: Optional[str] = None
        error: Optional[str] = None
        raw_response: Any = None
        retryable: bool = False

    err_val = d.get("error")
    retryable = d.get("ok", False) is False and _is_network_error(err_val)

    return _SendResult(
        success=d.get("ok", False),
        message_id=d.get("message_id"),
        error=err_val,
        raw_response=d,
        retryable=retryable,
    )
