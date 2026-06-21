import subprocess
import sys
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_bili_note.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_bili_note", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_run_bili_note_help_exposes_pipeline_options():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "--archive-dir" in result.stdout
    assert "--browser-target" in result.stdout
    assert "--subtitle-mode" in result.stdout
    assert "--download-images" in result.stdout
    assert "--dry-run" in result.stdout


def test_run_bili_note_detects_video_and_opus_sources():
    module = load_module()

    assert module.source_kind("https://www.bilibili.com/video/BV1abc/") == "video"
    assert module.find_source_id("https://www.bilibili.com/video/BV1abc/") == "BV1abc"
    assert module.source_kind("https://www.bilibili.com/opus/1194341967364882439?from=search") == "opus"
    assert module.find_source_id("https://www.bilibili.com/opus/1194341967364882439?from=search") == "1194341967364882439"
    assert module.source_kind("1194341967364882439") == "opus"
