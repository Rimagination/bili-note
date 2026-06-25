import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "extract_bilibili.py"


def load_module():
    spec = importlib.util.spec_from_file_location("extract_bilibili", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_help_exposes_asr_backend_options():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "--asr-backend" in result.stdout
    assert "--asr-model" in result.stdout
    assert "--asr-device" in result.stdout
    assert "--asr-compute-type" in result.stdout
    assert "--qwen-python" in result.stdout
    assert "--download-subtitles" in result.stdout


def test_resolve_asr_backend_auto_prefers_faster_whisper(monkeypatch):
    module = load_module()

    available = {"faster_whisper": True, "funasr": True, "whisper": True}

    def fake_find_spec(name):
        return object() if available.get(name) else None

    monkeypatch.setattr(module.importlib.util, "find_spec", fake_find_spec)
    monkeypatch.setattr(module, "qwen_available", lambda: False)

    assert module.resolve_asr_backend("auto", "en") == "faster-whisper"
    assert module.resolve_asr_backend("funasr") == "funasr"


def test_resolve_asr_backend_auto_prefers_qwen_for_chinese(monkeypatch):
    module = load_module()

    monkeypatch.setattr(module, "qwen_available", lambda: True)

    assert module.resolve_asr_backend("auto", "zh") == "qwen3-asr"
    assert module.resolve_asr_backend("auto", "Chinese") == "qwen3-asr"


def test_write_bilibili_subtitle_outputs(tmp_path):
    module = load_module()
    payload = {
        "body": [
            {"from": 0.0, "to": 1.2, "content": "第一句"},
            {"from": 1.2, "to": 3.4, "content": "第二句"},
        ]
    }

    outputs = module.write_bilibili_subtitle_outputs(payload, tmp_path, "p01_123", "zh-CN")

    assert Path(outputs["json"]).exists()
    assert Path(outputs["txt"]).read_text(encoding="utf-8") == "第一句\n第二句\n"
    srt = Path(outputs["srt"]).read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:01,200" in srt
    assert "00:00:01,200 --> 00:00:03,400" in srt
