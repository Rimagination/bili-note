#!/usr/bin/env python3
"""Check Bili Note runtime dependencies and optional extraction paths."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent

REQUIRED_SCRIPTS = (
    "run_bili_note.py",
    "extract_bilibili.py",
    "fetch_browser_ai_subtitles.py",
    "archive_bili_materials.py",
    "score_bili_note.py",
    "update_note_budget_section.py",
    "check_environment.py",
)

ASR_MODULES = {
    "faster_whisper": "faster-whisper",
    "funasr": "FunASR / SenseVoice",
    "whisper": "openai-whisper",
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
    api_check: Callable[[str, float], dict[str, Any]] = check_bilibili_api,
    cdp_url: str = "http://localhost:3456/targets",
    api_url: str = "https://api.bilibili.com/x/web-interface/nav",
    timeout: float = 0.7,
) -> dict[str, Any]:
    python = python_status()
    scripts = scripts_status(script_dir)
    commands = {
        "ffmpeg": command_status("ffmpeg", which),
        "yt-dlp": command_status("yt-dlp", which),
    }
    modules = {name: module_status(name, find_spec) for name in (*ASR_MODULES.keys(), "yt_dlp", "pytest")}
    web_access = web_check(cdp_url, timeout)
    bilibili_api = api_check(api_url, max(timeout, 1.5))

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
            "needs": ["network access to Bilibili public APIs"],
            "bilibili_api": bilibili_api,
            "python_packages": "stdlib only",
        },
        "browser_ai_subtitles": {
            "ok": bool(core_ok and web_access.get("ok")),
            "needs": ["Chrome", "web-access skill", "open logged-in Bilibili video tab", "CDP target id"],
            "supported_browser": "Chrome via web-access proxy",
            "unsupported_login_methods": [
                "copying browser profiles",
                "reading Cookie databases",
                "launching the user's real profile with a raw remote-debugging port",
            ],
            "web_access": web_access,
        },
        "audio_asr_fallback": {
            "ok": bool(core_ok and commands["ffmpeg"]["ok"] and asr_backend_ok),
            "needs": ["ffmpeg", "one ASR backend"],
            "asr_backends": {name: modules[name] for name in ASR_MODULES},
            "yt_dlp_available": yt_dlp_ok,
            "note": "yt-dlp is optional unless Bilibili API audio download fails.",
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
    if core_ok and not commands["ffmpeg"]["ok"]:
        recommendations.append("Install ffmpeg before using audio ASR fallback.")
    if core_ok and not asr_backend_ok:
        recommendations.append("Install faster-whisper, funasr, or openai-whisper before using audio ASR fallback.")
    if core_ok and not yt_dlp_ok:
        recommendations.append("Install yt-dlp only if public audio download fails or login cookies are needed.")
    if not modules["pytest"]["ok"]:
        recommendations.append("Install pytest only when you want to run this skill's tests.")

    return {
        "python": python,
        "scripts": scripts,
        "commands": commands,
        "modules": modules,
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
    print(f"- Public subtitles/comments/archive: {mark(capabilities['public_subtitles_comments_archive']['ok'])}")
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
    print(f"- Audio ASR fallback: {mark(capabilities['audio_asr_fallback']['ok'])}")
    print(f"  ffmpeg: {mark(report['commands']['ffmpeg']['ok'])}")
    print(
        "  ASR backends: "
        + ", ".join(f"{label}={mark(report['modules'][name]['ok'])}" for name, label in ASR_MODULES.items())
    )
    print(f"  yt-dlp optional: {mark(capabilities['audio_asr_fallback']['yt_dlp_available'])}")
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
    parser.add_argument("--api-url", default="https://api.bilibili.com/x/web-interface/nav", help="Bilibili public API probe endpoint")
    parser.add_argument("--timeout", type=float, default=0.7, help="CDP probe timeout in seconds")
    args = parser.parse_args()

    report = evaluate_environment(cdp_url=args.cdp_url, api_url=args.api_url, timeout=args.timeout)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human(report)

    if args.strict and not report["capabilities"]["core"]["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
