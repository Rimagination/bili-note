import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_environment.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_environment", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_check_environment_help_exposes_json_and_strict_options():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "--json" in result.stdout
    assert "--strict" in result.stdout
    assert "--cdp-url" in result.stdout
    assert "--api-url" in result.stdout


def test_evaluate_environment_reports_ready_optional_paths():
    module = load_module()

    def fake_which(name):
        return {"ffmpeg": "C:/tools/ffmpeg.exe", "yt-dlp": "C:/tools/yt-dlp.exe"}.get(name)

    def fake_find_spec(name):
        return object() if name in {"faster_whisper", "pytest"} else None

    def fake_web_check(cdp_url, timeout):
        return {"ok": True, "reachable": True, "target_count": 1, "url": cdp_url}

    def fake_api_check(api_url, timeout):
        return {"ok": True, "reachable": True, "url": api_url, "code": 0}

    report = module.evaluate_environment(
        script_dir=ROOT / "scripts",
        which=fake_which,
        find_spec=fake_find_spec,
        web_check=fake_web_check,
        api_check=fake_api_check,
    )

    assert report["capabilities"]["core"]["ok"]
    assert report["capabilities"]["public_subtitles_comments_archive"]["ok"]
    assert report["capabilities"]["browser_ai_subtitles"]["ok"]
    assert report["capabilities"]["audio_asr_fallback"]["ok"]
    assert report["capabilities"]["developer_tests"]["ok"]


def test_evaluate_environment_keeps_core_ready_when_optional_tools_are_missing():
    module = load_module()

    def fake_which(name):
        return None

    def fake_find_spec(name):
        return None

    def fake_web_check(cdp_url, timeout):
        return {"ok": False, "reachable": False, "target_count": 0, "url": cdp_url}

    def fake_api_check(api_url, timeout):
        return {"ok": True, "reachable": True, "url": api_url, "code": 0}

    report = module.evaluate_environment(
        script_dir=ROOT / "scripts",
        which=fake_which,
        find_spec=fake_find_spec,
        web_check=fake_web_check,
        api_check=fake_api_check,
    )

    assert report["capabilities"]["core"]["ok"]
    assert report["capabilities"]["public_subtitles_comments_archive"]["ok"]
    assert not report["capabilities"]["browser_ai_subtitles"]["ok"]
    assert not report["capabilities"]["audio_asr_fallback"]["ok"]
    assert not report["capabilities"]["developer_tests"]["ok"]
    assert any("ffmpeg" in item for item in report["recommendations"])
    assert any("ASR" in item for item in report["recommendations"])


def test_evaluate_environment_marks_public_route_unavailable_when_bilibili_api_fails():
    module = load_module()

    def fake_api_check(api_url, timeout):
        return {"ok": False, "reachable": False, "url": api_url, "error": "TimeoutError"}

    report = module.evaluate_environment(
        script_dir=ROOT / "scripts",
        which=lambda name: None,
        find_spec=lambda name: object() if name == "pytest" else None,
        web_check=lambda cdp_url, timeout: {"ok": False, "reachable": False, "target_count": 0, "url": cdp_url},
        api_check=fake_api_check,
    )

    assert report["capabilities"]["core"]["ok"]
    assert not report["capabilities"]["public_subtitles_comments_archive"]["ok"]
    assert any("Bilibili public APIs" in item for item in report["recommendations"])
