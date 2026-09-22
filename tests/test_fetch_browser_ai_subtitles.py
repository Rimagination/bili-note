import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCRIPT = SCRIPTS / "fetch_browser_ai_subtitles.py"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import edge_cdp


def load_module():
    spec = importlib.util.spec_from_file_location("fetch_browser_ai_subtitles", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_fetch_script_help_exposes_edge_route():
    import subprocess

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "--browser" in result.stdout
    assert "--edge-cdp-url" in result.stdout


def test_edge_target_selection_prefers_bilibili_page(monkeypatch):
    monkeypatch.setattr(
        edge_cdp,
        "_json_get",
        lambda url, timeout: [
            {"id": "other", "type": "page", "url": "https://example.com", "webSocketDebuggerUrl": "ws://other"},
            {
                "id": "bili",
                "type": "page",
                "url": "https://www.bilibili.com/video/BV1abc",
                "webSocketDebuggerUrl": "ws://bili",
            },
        ],
    )

    target = edge_cdp.select_target()

    assert target["targetId"] == "bili"


def test_edge_target_selection_rejects_ambiguous_video_pages(monkeypatch):
    monkeypatch.setattr(
        edge_cdp,
        "_json_get",
        lambda url, timeout: [
            {"id": "one", "type": "page", "url": "https://www.bilibili.com/video/BV1one", "webSocketDebuggerUrl": "ws://one"},
            {"id": "two", "type": "page", "url": "https://www.bilibili.com/video/BV1two", "webSocketDebuggerUrl": "ws://two"},
        ],
    )

    try:
        edge_cdp.select_target()
    except edge_cdp.EdgeCdpError as exc:
        assert "多个 B 站视频页" in str(exc)
    else:
        raise AssertionError("ambiguous Edge targets should require --target")


def test_page_count_works_with_direct_cdp_session():
    module = load_module()

    class FakeSession:
        def evaluate(self, expression, timeout=45):
            return {
                "value": {
                    "pages": [
                        {"index": 0, "page": 1, "cid": 123, "part": "P1"},
                        {"index": 1, "page": 2, "cid": 456, "part": "P2"},
                        {"index": 2, "page": 3, "cid": 789, "part": "P3"},
                    ],
                    "title": "Bilibili",
                    "url": "https://www.bilibili.com/video/BV1abc",
                }
            }

    assert module.page_count(FakeSession()) == 3


def test_subtitle_url_falls_back_to_v2():
    module = load_module()

    selected, resolved = module.select_subtitle(
        {"subtitles": [{"lan": "ai-zh", "subtitle_url": "", "subtitle_url_v2": "https://example.com/v2.json"}]}
    )

    assert resolved.endswith("/v2.json")
    assert selected["subtitle_url"] == resolved


def test_direct_cdp_session_sends_runtime_evaluate(monkeypatch):
    import websocket

    module = load_module()

    class FakeSocket:
        def __init__(self):
            self.messages = []

        def settimeout(self, timeout):
            self.timeout = timeout

        def send(self, message):
            self.messages.append(json.loads(message))

        def recv(self):
            return json.dumps({"id": 1, "result": {"result": {"value": {"ok": True}}}})

        def close(self):
            pass

    fake_socket = FakeSocket()
    monkeypatch.setattr(websocket, "create_connection", lambda *args, **kwargs: fake_socket)
    session = edge_cdp.DirectCdpSession({"webSocketDebuggerUrl": "ws://edge"})

    assert session.evaluate("({ok: true})") == {"value": {"ok": True}}
    assert fake_socket.messages[0]["method"] == "Runtime.evaluate"
    assert fake_socket.messages[0]["params"]["awaitPromise"] is True
    session.close()


def test_write_subtitle_outputs_returns_absolute_paths(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.chdir(tmp_path)

    files = module.write_subtitle_outputs({"body": [{"content": "字幕", "from": 0, "to": 1}]}, Path("extract"), "p01")

    assert Path(files["txt"]).is_absolute()
    assert Path(files["txt"]).exists()
