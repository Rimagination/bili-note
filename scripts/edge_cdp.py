"""Small direct-CDP adapter for a Microsoft Edge remote-debugging target.

The normal Bili Note browser route uses the web-access proxy. Edge exposes the
same Chromium DevTools Protocol through /json/list, so this module keeps the
Edge path optional and isolated from the zero-dependency core workflow.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class EdgeCdpError(RuntimeError):
    """Raised when Edge's direct DevTools endpoint cannot be used."""


def _json_get(url: str, timeout: float) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise EdgeCdpError(f"无法访问 Edge DevTools 端点：{url}；{exc}") from exc


def list_targets(cdp_url: str = "http://127.0.0.1:9222", timeout: float = 3.0) -> list[dict[str, Any]]:
    base = cdp_url.rstrip("/")
    payload = _json_get(f"{base}/json/list", timeout)
    if not isinstance(payload, list):
        raise EdgeCdpError("Edge /json/list 没有返回页面列表。")
    targets: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict) or item.get("type") != "page":
            continue
        target = dict(item)
        target["targetId"] = item.get("targetId") or item.get("id")
        targets.append(target)
    return targets


def select_target(
    cdp_url: str = "http://127.0.0.1:9222",
    target_id: str | None = None,
    timeout: float = 3.0,
) -> dict[str, Any]:
    targets = list_targets(cdp_url, timeout)
    if target_id:
        for target in targets:
            if target.get("targetId") == target_id or target.get("id") == target_id:
                return target
        raise EdgeCdpError(f"Edge 中找不到 target={target_id}；请重新读取 /json/list。")

    def is_bilibili(target: dict[str, Any]) -> bool:
        try:
            hostname = (urllib.parse.urlsplit(str(target.get("url") or "")).hostname or "").lower().rstrip(".")
        except ValueError:
            return False
        return hostname == "bilibili.com" or hostname.endswith(".bilibili.com")

    bili_targets = [target for target in targets if is_bilibili(target)]
    video_targets = [
        target
        for target in bili_targets
        if (urllib.parse.urlsplit(str(target.get("url") or "")).path or "").startswith("/video/")
    ]
    if len(video_targets) == 1:
        candidate = video_targets[0]
    elif len(video_targets) > 1:
        raise EdgeCdpError("Edge 中有多个 B 站视频页；请传入 --target 指定要读取的页面。")
    elif len(bili_targets) == 1:
        raise EdgeCdpError("Edge 中只有 B 站非视频页面；请打开一个 B 站视频页，或传入 --target。")
    elif len(bili_targets) > 1:
        raise EdgeCdpError("Edge 中有多个 B 站页面但没有明确的视频页；请传入 --target。")
    else:
        raise EdgeCdpError("Edge 没有可用的 B 站视频页面；请登录 B 站并打开视频页，或传入 --target。")
    if not candidate.get("webSocketDebuggerUrl"):
        raise EdgeCdpError("选中的 Edge B 站视频页没有 webSocketDebuggerUrl；请确认使用了远程调试端口。")
    return candidate


class DirectCdpSession:
    """Evaluate JavaScript in one Edge page through its CDP WebSocket."""

    def __init__(self, target: dict[str, Any], timeout: float = 45.0) -> None:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise EdgeCdpError("选中的 Edge 页面缺少 webSocketDebuggerUrl。")
        try:
            import websocket  # type: ignore
        except ImportError as exc:
            raise EdgeCdpError(
                "Edge 直连需要 websocket-client；请运行 python -m pip install websocket-client。"
            ) from exc
        try:
            self._socket = websocket.create_connection(
                websocket_url,
                timeout=timeout,
                enable_multithread=True,
                suppress_origin=True,
            )
        except Exception as exc:
            raise EdgeCdpError(f"无法连接 Edge CDP WebSocket：{exc}") from exc
        self._socket.settimeout(timeout)
        self._next_id = 0

    def evaluate(self, expression: str, timeout: float = 45.0) -> dict[str, Any]:
        self._next_id += 1
        command_id = self._next_id
        message = {
            "id": command_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
                "userGesture": True,
            },
        }
        try:
            self._socket.settimeout(timeout)
            self._socket.send(json.dumps(message, ensure_ascii=False))
            while True:
                raw = self._socket.recv()
                if not raw:
                    raise EdgeCdpError("Edge CDP WebSocket 提前关闭。")
                payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                if payload.get("id") != command_id:
                    continue
                if payload.get("error"):
                    raise EdgeCdpError(f"Edge CDP 执行失败：{payload['error']}")
                result = payload.get("result") or {}
                exception = result.get("exceptionDetails")
                if exception:
                    description = exception.get("text") or exception.get("exception", {}).get("description")
                    raise EdgeCdpError(f"Edge 页面脚本执行失败：{description or exception}")
                value = (result.get("result") or {}).get("value")
                return {"value": value}
        except EdgeCdpError:
            raise
        except Exception as exc:
            raise EdgeCdpError(f"Edge CDP 执行超时或连接失败：{exc}") from exc

    def close(self) -> None:
        try:
            self._socket.close()
        except Exception:
            pass

    def __enter__(self) -> "DirectCdpSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
