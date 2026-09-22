#!/usr/bin/env python3
"""Check Bili Note runtime dependencies and optional extraction paths."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent

REQUIRED_SCRIPTS = (
    "run_bili_note.py",
    "extract_bilibili.py",
    "extract_bilibili_opus.py",
    "fetch_browser_ai_subtitles.py",
    "edge_cdp.py",
    "extract_video_keyframes.py",
    "archive_bili_materials.py",
    "score_bili_note.py",
    "update_note_budget_section.py",
    "run_qwen_asr.py",
    "setup_qwen_asr_env.py",
    "check_environment.py",
)

ASR_MODULES = {
    "faster_whisper": "faster-whisper",
    "funasr": "FunASR / SenseVoice",
    "whisper": "openai-whisper",
}


def shared_cache_dir() -> Path:
    return Path(os.environ.get("RIMAGINATION_NOTE_CACHE", Path.home() / ".cache" / "rimagination-notes")).expanduser()


def qwen_venv_python_paths(venv: Path) -> list[Path]:
    return [venv / "Scripts" / "python.exe", venv / "bin" / "python"]


def qwen_python_candidates() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("RIMAGINATION_QWEN_PYTHON", "BILI_NOTE_QWEN_PYTHON", "DOUYIN_NOTE_QWEN_PYTHON"):
        if os.environ.get(env_name):
            candidates.append(Path(os.environ[env_name]).expanduser())
    for venv in [
        shared_cache_dir() / "qwen3-asr-venv",
        Path.home() / ".cache" / "dy-note" / "qwen3-asr-venv",
        Path.home() / ".cache" / "douyin-note" / "qwen3-asr-venv",
    ]:
        candidates.extend(qwen_venv_python_paths(venv))
    return candidates


def probe_qwen_python(find_spec: Callable[[str], object | None] = importlib.util.find_spec) -> dict[str, Any]:
    if module_status("qwen_asr", find_spec)["ok"]:
        return {"ok": True, "python": sys.executable, "source": "current-python"}

    probe_code = "import qwen_asr, json, sys; print(json.dumps({'python': sys.executable, 'qwen_asr': 'OK'}))"
    existing = [path for path in qwen_python_candidates() if path.exists()]
    for python in existing:
        try:
            result = subprocess.run(
                [str(python), "-c", probe_code],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
        except Exception as exc:
            return {"ok": False, "python": str(python), "error": type(exc).__name__, "message": str(exc)}
        if result.returncode == 0:
            return {"ok": True, "python": str(python), "source": "shared-or-legacy-venv"}
    return {
        "ok": False,
        "python": None,
        "candidates": [str(path) for path in qwen_python_candidates()],
        "hint": "Run scripts/setup_qwen_asr_env.py to create the shared Qwen3-ASR environment.",
    }


def python_status() -> dict[str, Any]:
    version = ".".join(str(part) for part in sys.version_info[:3])
    return {
        "ok": sys.version_info >= (3, 10),
        "version": version,
        "required": ">=3.10",
    }


def scripts_status(script_dir: Path = SCRIPT_DIR) -> dict[str, Any]:
    missing = [name for name in REQUIRED_SCRIPTS if not (script_dir / name).exists()]
    return {
        "ok": not missing,
        "script_dir": str(script_dir),
        "missing": missing,
    }


def command_status(name: str, which: Callable[[str], str | None] = shutil.which) -> dict[str, Any]:
    path = which(name)
    return {"ok": bool(path), "path": path}


def module_status(
    name: str,
    find_spec: Callable[[str], object | None] = importlib.util.find_spec,
) -> dict[str, Any]:
    try:
        spec = find_spec(name)
    except Exception as exc:  # pragma: no cover - defensive for broken installs
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)}
    return {"ok": spec is not None}


def check_web_access(cdp_url: str = "http://localhost:3456/targets", timeout: float = 0.7) -> dict[str, Any]:
    try:
        req = urllib.request.Request(cdp_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw or "[]")
    except Exception as exc:
        return {
            "ok": False,
            "reachable": False,
            "target_count": 0,
            "url": cdp_url,
            "error": type(exc).__name__,
            "message": str(exc),
        }

    target_count = len(data) if isinstance(data, list) else 0
    return {
        "ok": target_count > 0,
        "reachable": True,
        "target_count": target_count,
        "url": cdp_url,
    }


def check_edge_cdp(cdp_url: str = "http://127.0.0.1:9222", timeout: float = 0.7) -> dict[str, Any]:
    endpoint = f"{cdp_url.rstrip('/')}/json/list"
    try:
        req = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw or "[]")
    except Exception as exc:
        return {
            "ok": False,
            "reachable": False,
            "target_count": 0,
            "bilibili_video_target": False,
            "url": endpoint,
            "error": type(exc).__name__,
            "message": str(exc),
        }

    targets = data if isinstance(data, list) else []
    video_target = False
    for item in targets:
        if not isinstance(item, dict) or item.get("type") != "page":
            continue
        parsed = urllib.parse.urlsplit(str(item.get("url") or ""))
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if (hostname == "bilibili.com" or hostname.endswith(".bilibili.com")) and parsed.path.startswith("/video/"):
            video_target = True
            break
    return {
        "ok": video_target,
        "reachable": True,
        "target_count": len(targets),
        "bilibili_video_target": video_target,
        "url": endpoint,
    }


def check_bilibili_api(api_url: str = "https://api.bilibili.com/x/web-interface/nav", timeout: float = 1.5) -> dict[str, Any]:
    try:
        req = urllib.request.Request(
            api_url,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
                ),
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw or "{}")
    except Exception as exc:
        return {
            "ok": False,
            "reachable": False,
            "url": api_url,
            "error": type(exc).__name__,
            "message": str(exc),
        }

    return {
        "ok": isinstance(data, dict) and "code" in data,
        "reachable": True,
        "url": api_url,
        "code": data.get("code") if isinstance(data, dict) else None,
        "message": data.get("message") if isinstance(data, dict) else None,
    }


def evaluate_environment(
    script_dir: Path = SCRIPT_DIR,
    which: Callable[[str], str | None] = shutil.which,
    find_spec: Callable[[str], object | None] = importlib.util.find_spec,
    web_check: Callable[[str, float], dict[str, Any]] = check_web_access,
    edge_check: Callable[[str, float], dict[str, Any]] = check_edge_cdp,
    api_check: Callable[[str, float], dict[str, Any]] = check_bilibili_api,
    qwen_probe: Callable[[Callable[[str], object | None]], dict[str, Any]] = probe_qwen_python,
    cdp_url: str = "http://localhost:3456/targets",
    edge_cdp_url: str = "http://127.0.0.1:9222",
    api_url: str = "https://api.bilibili.com/x/web-interface/nav",
    timeout: float = 0.7,
) -> dict[str, Any]:
    python = python_status()
    scripts = scripts_status(script_dir)
    commands = {
        "ffmpeg": command_status("ffmpeg", which),
        "yt-dlp": command_status("yt-dlp", which),
    }
    modules = {name: module_status(name, find_spec) for name in (*ASR_MODULES.keys(), "yt_dlp", "websocket", "pytest")}
    web_access = web_check(cdp_url, timeout)
    edge_cdp = edge_check(edge_cdp_url, timeout)
    bilibili_api = api_check(api_url, max(timeout, 1.5))
    qwen = qwen_probe(find_spec)
    shared_cache = shared_cache_dir()

    core_ok = bool(python["ok"] and scripts["ok"])
    public_route_ok = bool(core_ok and bilibili_api.get("ok"))
    asr_backend_ok = any(modules[name]["ok"] for name in ASR_MODULES)
    yt_dlp_ok = bool(commands["yt-dlp"]["ok"] or modules["yt_dlp"]["ok"])

    capabilities = {
        "core": {
            "ok": core_ok,
            "needs": ["Python >=3.10", "bundled Bili Note scripts"],
        },
        "public_subtitles_comments_archive": {
            "ok": public_route_ok,
            "needs": ["network access to Bilibili public APIs and public opus pages"],
            "bilibili_api": bilibili_api,
            "python_packages": "stdlib only",
        },
        "browser_ai_subtitles": {
            "ok": bool(core_ok and web_access.get("ok")),
            "needs": ["Chrome", "web-access skill", "open logged-in Bilibili video tab", "CDP target id"],
            "supported_browser": "Chrome via web-access proxy",
            "web_access": web_access,
        },
        "edge_browser_ai_subtitles": {
            "ok": bool(core_ok and modules["websocket"]["ok"] and edge_cdp.get("ok")),
            "dependency_ready": bool(core_ok and modules["websocket"]["ok"]),
            "endpoint_reachable": bool(edge_cdp.get("reachable")),
            "bilibili_video_target": bool(edge_cdp.get("bilibili_video_target")),
            "needs": ["Microsoft Edge started with remote debugging", "websocket-client", "open logged-in Bilibili video tab"],
            "supported_browser": "Microsoft Edge via direct CDP",
            "websocket_client": modules["websocket"],
            "edge_cdp": edge_cdp,
            "note": "Pass --browser edge; the default endpoint is http://127.0.0.1:9222.",
        },
        "audio_asr_fallback": {
            "ok": bool(core_ok and commands["ffmpeg"]["ok"] and (qwen.get("ok") or asr_backend_ok)),
            "needs": ["ffmpeg", "Qwen3-ASR for Chinese or one Whisper-family ASR backend for foreign-language video"],
            "preferred_for_zh": "qwen3-asr",
            "qwen3_asr": qwen,
            "asr_backends": {name: modules[name] for name in ASR_MODULES},
            "yt_dlp_available": yt_dlp_ok,
            "note": "yt-dlp is optional unless Bilibili API audio download fails.",
        },
        "keyframe_visual_review": {
            "ok": bool(core_ok and commands["ffmpeg"]["ok"]),
            "needs": ["ffmpeg", "a public Bilibili video stream or yt-dlp", "a vision-capable model for interpretation"],
            "ffmpeg": commands["ffmpeg"],
            "yt_dlp_available": yt_dlp_ok,
            "note": "The runner creates one 4x3 contact sheet with up to 12 representative frames; visual interpretation is performed by the active Agent.",
        },
        "developer_tests": {
            "ok": bool(modules["pytest"]["ok"]),
            "needs": ["pytest"],
        },
    }

    recommendations: list[str] = []
    if not python["ok"]:
        recommendations.append(f"Use Python {python['required']}; current version is {python['version']}.")
    if not scripts["ok"]:
        recommendations.append("Reinstall or repair the skill; some bundled scripts are missing.")
    if core_ok and not bilibili_api.get("ok"):
        recommendations.append("Check network access to Bilibili public APIs before running the default extraction path.")
    if core_ok and not web_access.get("ok"):
        recommendations.append("Browser AI subtitles need Chrome + web-access plus an opened logged-in Bilibili video page.")
    if core_ok and not modules["websocket"]["ok"]:
        recommendations.append("Edge browser AI subtitles need the optional websocket-client package: python -m pip install websocket-client.")
    if core_ok and modules["websocket"]["ok"] and not edge_cdp.get("reachable"):
        recommendations.append("Start Edge with --remote-debugging-port=9222 before using --browser edge.")
    elif core_ok and modules["websocket"]["ok"] and not edge_cdp.get("bilibili_video_target"):
        recommendations.append("Open a logged-in Bilibili video tab in the Edge remote-debugging instance before using --browser edge.")
    if core_ok and not commands["ffmpeg"]["ok"]:
        recommendations.append("Install ffmpeg before using audio ASR fallback.")
        recommendations.append("Install ffmpeg before using keyframe visual review.")
    if core_ok and not qwen.get("ok"):
        recommendations.append("For Chinese videos, run scripts/setup_qwen_asr_env.py once to set up Qwen3-ASR; DyNote and Bili Note will share it.")
    if core_ok and not asr_backend_ok:
        recommendations.append("Install faster-whisper or openai-whisper when you need foreign-language video transcription.")
    if core_ok and not yt_dlp_ok:
        recommendations.append("Install yt-dlp only if public audio download fails or login cookies are needed.")
    if not modules["pytest"]["ok"]:
        recommendations.append("Install pytest only when you want to run this skill's tests.")

    return {
        "python": python,
        "scripts": scripts,
        "commands": commands,
        "modules": modules,
        "shared_resources": {
            "cache_dir": str(shared_cache),
            "qwen3_asr_venv": str(shared_cache / "qwen3-asr-venv"),
            "huggingface_cache": os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface"),
            "whisper_cache": str(Path.home() / ".cache" / "whisper"),
            "faster_whisper_cache": str(Path.home() / ".cache" / "faster-whisper"),
        },
        "qwen3_asr": qwen,
        "bilibili_api": bilibili_api,
        "capabilities": capabilities,
        "recommendations": recommendations,
    }


def mark(ok: bool) -> str:
    return "OK" if ok else "MISSING"


def print_human(report: dict[str, Any]) -> None:
    capabilities = report["capabilities"]
    print("Bili Note environment check")
    print("")
    print(f"- Core workflow: {mark(capabilities['core']['ok'])}")
    print(f"  Python: {report['python']['version']} (required {report['python']['required']})")
    if report["scripts"]["missing"]:
        print(f"  Missing scripts: {', '.join(report['scripts']['missing'])}")
    else:
        print("  Bundled scripts: OK")
    print(f"- Public subtitles/opus/comments/archive: {mark(capabilities['public_subtitles_comments_archive']['ok'])}")
    api = capabilities["public_subtitles_comments_archive"]["bilibili_api"]
    print(f"  Bilibili API: {'reachable' if api.get('reachable') else 'not reachable'}")
    print("  Python packages: stdlib only")
    print(f"- Browser AI subtitles (Chrome + web-access): {mark(capabilities['browser_ai_subtitles']['ok'])}")
    web_access = capabilities["browser_ai_subtitles"]["web_access"]
    print(
        "  web-access: "
        f"{'reachable' if web_access.get('reachable') else 'not reachable'}, "
        f"targets={web_access.get('target_count', 0)}"
    )
    print(f"- Browser AI subtitles (Edge direct CDP): {mark(capabilities['edge_browser_ai_subtitles']['ok'])}")
    edge_cdp = capabilities["edge_browser_ai_subtitles"]["edge_cdp"]
    print(
        "  Edge CDP: "
        f"{'reachable' if edge_cdp.get('reachable') else 'not reachable'}, "
        f"video_targets={'yes' if edge_cdp.get('bilibili_video_target') else 'no'}"
    )
    print(f"- Audio ASR fallback: {mark(capabilities['audio_asr_fallback']['ok'])}")
    print(f"  ffmpeg: {mark(report['commands']['ffmpeg']['ok'])}")
    print(f"  Qwen3-ASR for Chinese: {mark(report['qwen3_asr']['ok'])}")
    print(
        "  Whisper-family for foreign languages: "
        + ", ".join(f"{label}={mark(report['modules'][name]['ok'])}" for name, label in ASR_MODULES.items())
    )
    print(f"  yt-dlp optional: {mark(capabilities['audio_asr_fallback']['yt_dlp_available'])}")
    print(f"- Keyframe visual review: {mark(capabilities['keyframe_visual_review']['ok'])}")
    print(f"  yt-dlp fallback: {mark(capabilities['keyframe_visual_review']['yt_dlp_available'])}")
    print(f"- Shared cache: {report['shared_resources']['cache_dir']}")
    print(f"- Developer tests: {mark(capabilities['developer_tests']['ok'])}")

    if report["recommendations"]:
        print("")
        print("Recommendations")
        for item in report["recommendations"]:
            print(f"- {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when the core workflow is unavailable")
    parser.add_argument("--cdp-url", default="http://localhost:3456/targets", help="web-access targets endpoint")
    parser.add_argument("--edge-cdp-url", default="http://127.0.0.1:9222", help="Edge remote-debugging HTTP endpoint")
    parser.add_argument("--api-url", default="https://api.bilibili.com/x/web-interface/nav", help="Bilibili public API probe endpoint")
    parser.add_argument("--timeout", type=float, default=0.7, help="CDP probe timeout in seconds")
    args = parser.parse_args()

    report = evaluate_environment(
        cdp_url=args.cdp_url,
        edge_cdp_url=args.edge_cdp_url,
        api_url=args.api_url,
        timeout=args.timeout,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human(report)

    if args.strict and not report["capabilities"]["core"]["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
