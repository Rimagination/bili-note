"""One-command Bili Note extraction runner.

This script orchestrates the stable, non-LLM parts of the workflow:
metadata, subtitles, comments, archive, and evidence indexes. It intentionally
does not write the final analytical summary; Codex should read the archive and
write the user-facing Markdown note.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
EXTRACT_SCRIPT = SCRIPT_DIR / "extract_bilibili.py"
EXTRACT_OPUS_SCRIPT = SCRIPT_DIR / "extract_bilibili_opus.py"
BROWSER_AI_SCRIPT = SCRIPT_DIR / "fetch_browser_ai_subtitles.py"
ARCHIVE_SCRIPT = SCRIPT_DIR / "archive_bili_materials.py"


def configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


configure_stdout()


def safe_slug(value: str, default: str = "video") -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value, flags=re.UNICODE).strip("_")
    return value[:90] or default


def find_bvid(source: str) -> str:
    match = re.search(r"BV[0-9A-Za-z]+", source)
    return match.group(0) if match else safe_slug(source, "bili")


def source_kind(source: str) -> str:
    if re.search(r"(?:opus|dynamic)/\d+", source) or re.fullmatch(r"\d{12,}", source.strip()):
        return "opus"
    return "video"


def find_source_id(source: str) -> str:
    if source_kind(source) == "opus":
        match = re.search(r"(?:opus|dynamic)/(\d+)", source)
        if not match:
            match = re.search(r"\b(\d{12,})\b", source)
        return match.group(1) if match else safe_slug(source, "opus")
    return find_bvid(source)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_cmd(cmd: list[str], *, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"cmd": cmd, "returncode": 0, "skipped": True, "reason": "dry_run"}
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    result = subprocess.run(cmd, text=True, capture_output=True, encoding="utf-8", errors="replace", env=env)
    return {
        "cmd": cmd,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def command_text(cmd: list[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in cmd)


def public_subtitle_count(work_dir: Path) -> int:
    path = work_dir / "subtitle_manifest.json"
    if not path.exists() or path.stat().st_size <= 2:
        return 0
    try:
        data = read_json(path)
    except json.JSONDecodeError:
        return 0
    return len(data) if isinstance(data, list) else 0


def browser_subtitle_status(work_dir: Path) -> tuple[int, int]:
    for name in ("browser_ai_subtitle_manifest.json", "browser_subtitle_manifest.json"):
        path = work_dir / name
        if path.exists():
            data = read_json(path)
            return int(data.get("count") or 0), int(data.get("downloaded") or 0)
    return 0, 0


def comments_available(work_dir: Path) -> bool:
    return (work_dir / "comments_raw.json").exists()


def metadata_available(work_dir: Path) -> bool:
    return (work_dir / "metadata.json").exists()


def archive_available(archive_dir: Path | None) -> bool:
    if not archive_dir:
        return False
    return (archive_dir / "indexes" / "证据索引.jsonl").exists()


def article_available(work_dir: Path) -> bool:
    return (work_dir / "article_content.md").exists() and (work_dir / "article_evidence.jsonl").exists()


def summarize_outputs(work_dir: Path, archive_dir: Path | None) -> dict[str, Any]:
    public_subtitles = public_subtitle_count(work_dir)
    browser_count, browser_downloaded = browser_subtitle_status(work_dir)
    summary: dict[str, Any] = {
        "work_dir": str(work_dir),
        "metadata": metadata_available(work_dir),
        "public_subtitle_tracks": public_subtitles,
        "browser_ai_subtitle_parts": browser_count,
        "browser_ai_subtitle_downloaded": browser_downloaded,
        "article_content": article_available(work_dir),
        "images_manifest": (work_dir / "images_manifest.json").exists(),
        "comments": comments_available(work_dir),
    }
    if archive_dir:
        summary["archive_dir"] = str(archive_dir)
        for rel in (
            "indexes/图文全集.jsonl",
            "indexes/图文证据索引.jsonl",
            "indexes/字幕全集.jsonl",
            "indexes/字幕证据索引.jsonl",
            "indexes/评论全集.jsonl",
            "indexes/证据索引.jsonl",
        ):
            path = archive_dir / rel
            if path.exists():
                summary[rel] = {
                    "path": str(path),
                    "lines": sum(1 for _ in path.open(encoding="utf-8")),
                }
    return summary


def write_report(work_dir: Path, archive_dir: Path | None, steps: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    report = {
        "steps": steps,
        "summary": summary,
    }
    write_json(work_dir / "bili_note_run_report.json", report)
    md = ["# Bili Note Run Report", "", "## Summary", ""]
    for key, value in summary.items():
        md.append(f"- {key}: {value}")
    md.extend(["", "## Steps", ""])
    for step in steps:
        status = "skipped" if step.get("skipped") else ("ok" if step.get("returncode") == 0 else "failed")
        md.append(f"### {step.get('name', 'step')} - {status}")
        if step.get("reason"):
            md.append(f"- reason: {step['reason']}")
        if step.get("cmd"):
            md.append(f"- command: `{command_text(step['cmd'])}`")
        if step.get("returncode") not in (None, 0):
            md.append(f"- returncode: {step['returncode']}")
        md.append("")
    if archive_dir:
        md.extend(
            [
                "## Next",
                "",
                "Use the evidence index when writing the final note:",
                "",
                f"- `{archive_dir / 'indexes' / '证据索引.jsonl'}`",
                f"- `{archive_dir / 'indexes' / '字幕全集.md'}`",
                "",
            ]
        )
    (work_dir / "bili_note_run_report.md").write_text("\n".join(md), encoding="utf-8")


def append_step(steps: list[dict[str, Any]], name: str, result: dict[str, Any]) -> None:
    result = {"name": name, **result}
    steps.append(result)
    status = "SKIP" if result.get("skipped") else ("OK" if result.get("returncode") == 0 else "FAIL")
    print(f"[{status}] {name}", flush=True)
    if result.get("returncode") not in (None, 0):
        if result.get("stderr"):
            print(result["stderr"], file=sys.stderr)
        raise SystemExit(result["returncode"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Bili Note extraction, archive, and evidence indexing")
    parser.add_argument("source", help="Bilibili video/opus URL, BVID, or opus id")
    parser.add_argument("--work-dir", help="Temporary extraction directory")
    parser.add_argument("--archive-dir", help="Permanent archive directory")
    parser.add_argument("--parts", default="all", help="'all', 'key', or comma-separated page numbers")
    parser.add_argument("--comments", action="store_true", help="Fetch comments")
    parser.add_argument(
        "--download-images",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Download opus/article images when source is a Bilibili opus page",
    )
    parser.add_argument("--browser-target", help="web-access CDP target id for browser AI subtitles")
    parser.add_argument("--subtitle-mode", choices=["auto", "public", "browser", "none"], default="auto")
    parser.add_argument("--archive", action=argparse.BooleanOptionalAction, default=True, help="Archive materials when archive-dir is set")
    parser.add_argument("--force", action="store_true", help="Re-run stages even if outputs exist")
    parser.add_argument("--dry-run", action="store_true", help="Print planned stages without running them")
    args = parser.parse_args()

    source_id = find_source_id(args.source)
    work_dir = Path(args.work_dir) if args.work_dir else Path.cwd() / f"tmp_bili_note_{safe_slug(source_id)}"
    archive_dir = Path(args.archive_dir) if args.archive_dir else None
    work_dir.mkdir(parents=True, exist_ok=True)
    steps: list[dict[str, Any]] = []
    kind = source_kind(args.source)

    if kind == "opus":
        need_extract = args.force or not article_available(work_dir)
        if need_extract:
            cmd = [sys.executable, str(EXTRACT_OPUS_SCRIPT), args.source, "--out", str(work_dir)]
            if not args.download_images:
                cmd.append("--no-download-images")
            if args.comments:
                cmd.append("--comments")
            if args.force:
                cmd.append("--force")
            append_step(steps, "opus_content_images", run_cmd(cmd, dry_run=args.dry_run))
        else:
            append_step(
                steps,
                "opus_content_images",
                {"skipped": True, "reason": "article content already available", "returncode": 0},
            )
        if args.archive and archive_dir:
            if args.force or not archive_available(archive_dir):
                cmd = [
                    sys.executable,
                    str(ARCHIVE_SCRIPT),
                    "--extract-dir",
                    str(work_dir),
                    "--archive-dir",
                    str(archive_dir),
                ]
                append_step(steps, "archive_materials", run_cmd(cmd, dry_run=args.dry_run))
            else:
                append_step(
                    steps,
                    "archive_materials",
                    {"skipped": True, "reason": "archive evidence index already exists", "returncode": 0},
                )
        elif args.archive and not archive_dir:
            append_step(
                steps,
                "archive_materials",
                {"skipped": True, "reason": "no --archive-dir provided", "returncode": 0},
            )

        summary = summarize_outputs(work_dir, archive_dir)
        summary["kind"] = "opus"
        write_report(work_dir, archive_dir, steps, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return 0

    need_extract = args.force or not metadata_available(work_dir)
    need_public_subtitles = args.subtitle_mode in ("auto", "public") and (args.force or public_subtitle_count(work_dir) == 0)
    need_comments = args.comments and (args.force or not comments_available(work_dir))

    if need_extract or need_public_subtitles or need_comments:
        cmd = [sys.executable, str(EXTRACT_SCRIPT), args.source, "--out", str(work_dir), "--parts", args.parts]
        if args.subtitle_mode in ("auto", "public"):
            cmd.append("--download-subtitles")
        if args.comments:
            cmd.append("--comments")
        if args.force:
            cmd.append("--force")
        append_step(steps, "metadata_public_subtitles_comments", run_cmd(cmd, dry_run=args.dry_run))
    else:
        append_step(
            steps,
            "metadata_public_subtitles_comments",
            {"skipped": True, "reason": "metadata/subtitles/comments already available", "returncode": 0},
        )

    public_tracks = public_subtitle_count(work_dir)
    browser_count, browser_downloaded = browser_subtitle_status(work_dir)
    need_browser = args.subtitle_mode == "browser" or (
        args.subtitle_mode == "auto" and public_tracks == 0 and browser_downloaded == 0
    )
    if need_browser:
        if args.browser_target:
            cmd = [
                sys.executable,
                str(BROWSER_AI_SCRIPT),
                "--target",
                args.browser_target,
                "--out",
                str(work_dir),
            ]
            if args.force:
                # The browser subtitle script overwrites manifest outputs naturally.
                pass
            append_step(steps, "browser_ai_subtitles", run_cmd(cmd, dry_run=args.dry_run))
        else:
            append_step(
                steps,
                "browser_ai_subtitles",
                {
                    "skipped": True,
                    "reason": "public subtitles unavailable and no --browser-target provided",
                    "returncode": 0,
                },
            )
    else:
        append_step(
            steps,
            "browser_ai_subtitles",
            {
                "skipped": True,
                "reason": f"not needed; public_tracks={public_tracks}, browser_downloaded={browser_downloaded}",
                "returncode": 0,
            },
        )

    if args.archive and archive_dir:
        if args.force or not archive_available(archive_dir):
            cmd = [
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "--extract-dir",
                str(work_dir),
                "--archive-dir",
                str(archive_dir),
            ]
            append_step(steps, "archive_materials", run_cmd(cmd, dry_run=args.dry_run))
        else:
            append_step(
                steps,
                "archive_materials",
                {"skipped": True, "reason": "archive evidence index already exists", "returncode": 0},
            )
    elif args.archive and not archive_dir:
        append_step(
            steps,
            "archive_materials",
            {"skipped": True, "reason": "no --archive-dir provided", "returncode": 0},
        )

    summary = summarize_outputs(work_dir, archive_dir)
    write_report(work_dir, archive_dir, steps, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
