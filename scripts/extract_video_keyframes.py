#!/usr/bin/env python3
"""Create a small, token-conscious keyframe contact sheet for a Bilibili video."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from extract_bilibili import (  # noqa: E402
    api_get,
    download_file,
    extract_bvid,
    headers,
    normalize_media_url,
    select_pages,
)


GRID_COLUMNS = 4
GRID_ROWS = 3
FRAME_WIDTH = 960
FRAME_HEIGHT = 540
CELL_WIDTH = 320
CELL_HEIGHT = 180


def configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


configure_stdout()


def format_clock(seconds: float | int | None) -> str:
    total = max(0, int(round(float(seconds or 0))))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def video_stem(page: dict[str, Any]) -> str:
    page_number = int(page.get("page") or 0)
    cid = str(page.get("cid") or "")
    if page_number < 1 or not cid.isdigit():
        raise RuntimeError("Bilibili 分P的 page/cid 不是安全的数字标识")
    return f"p{page_number:02d}_{cid}"


def choose_video_url(play: dict[str, Any]) -> str:
    data = play.get("data") or {}
    dash = data.get("dash") or {}
    videos = [item for item in dash.get("video") or [] if item.get("baseUrl") or item.get("base_url")]
    if videos:
        low_resolution = [item for item in videos if int(item.get("height") or 0) <= 480]
        candidates = low_resolution or videos
        selected = max(
            candidates,
            key=lambda item: (int(item.get("height") or 0), int(item.get("bandwidth") or 0)),
        )
        return normalize_media_url(selected.get("baseUrl") or selected.get("base_url") or "")

    durl = [item for item in data.get("durl") or [] if item.get("url")]
    if durl:
        return normalize_media_url(durl[0]["url"])
    raise RuntimeError("Bilibili 播放接口没有返回可用的视频流")


def existing_video(video_dir: Path, page: dict[str, Any]) -> Path | None:
    stem = video_stem(page)
    candidates = sorted(
        path
        for path in video_dir.glob(f"{stem}.*")
        if path.is_file()
        and not path.name.endswith(".part")
        and path.suffix.lower() not in {".json", ".txt", ".srt", ".wav", ".png"}
    )
    return candidates[0] if candidates else None


def download_video_with_bilibili_api(
    bvid: str,
    page: dict[str, Any],
    video_dir: Path,
    force: bool = False,
) -> Path:
    video_dir.mkdir(parents=True, exist_ok=True)
    if not force:
        cached = existing_video(video_dir, page)
        if cached:
            return cached

    play = api_get(
        "/x/player/playurl",
        {"bvid": bvid, "cid": str(page["cid"]), "qn": 32, "fnval": 16, "fourk": 1},
        bvid,
    )
    url = choose_video_url(play)
    if not url:
        raise RuntimeError(f"没有拿到 P{page.get('page')} 的视频 URL")
    output = video_dir / f"{video_stem(page)}.video.m4s"
    partial = output.with_name(output.name + ".part")
    try:
        partial.unlink(missing_ok=True)
        download_file(url, partial, bvid)
        partial.replace(output)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return output


def ytdlp_command() -> list[str]:
    executable = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    if executable:
        return [executable]
    raise RuntimeError("未找到 yt-dlp；可以安装 yt-dlp，或改用可访问 B 站播放接口的环境")


def download_video_with_ytdlp(
    bvid: str,
    page: dict[str, Any],
    video_dir: Path,
    cookies_from_browser: str | None = None,
    force: bool = False,
) -> Path:
    video_dir.mkdir(parents=True, exist_ok=True)
    if not force:
        cached = existing_video(video_dir, page)
        if cached:
            return cached

    template = str(video_dir / f"{video_stem(page)}.%(ext)s")
    url = f"https://www.bilibili.com/video/{bvid}/"
    if int(page.get("page") or 1) > 1:
        url += f"?p={int(page['page'])}"
    cmd = [
        *ytdlp_command(),
        "--no-playlist",
        "--add-header",
        f"Referer: https://www.bilibili.com/video/{bvid}/",
        "--add-header",
        f"User-Agent: {headers(bvid)['User-Agent']}",
        "-f",
        "bv*[height<=480]/b[height<=480]/bv/b",
        "-o",
        template,
    ]
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    cmd.append(url)
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"yt-dlp 下载 P{page.get('page')} 视频失败") from exc
    cached = existing_video(video_dir, page)
    if not cached:
        raise RuntimeError(f"yt-dlp 没有生成 P{page.get('page')} 视频文件")
    return cached


def resolve_video(
    bvid: str,
    page: dict[str, Any],
    video_dir: Path,
    source: str,
    cookies_from_browser: str | None = None,
    force: bool = False,
) -> tuple[Path, str]:
    errors: list[str] = []
    if source in {"auto", "bilibili-api"}:
        try:
            return download_video_with_bilibili_api(bvid, page, video_dir, force), "bilibili-api"
        except Exception as exc:
            errors.append(f"bilibili-api: {exc}")
    if source in {"auto", "yt-dlp"}:
        try:
            return (
                download_video_with_ytdlp(bvid, page, video_dir, cookies_from_browser, force),
                "yt-dlp",
            )
        except Exception as exc:
            errors.append(f"yt-dlp: {exc}")
    raise RuntimeError("；".join(errors) or "没有可用的视频来源")


def local_video(video_dir: Path, page: dict[str, Any]) -> Path:
    cached = existing_video(video_dir, page)
    if not cached:
        raise RuntimeError(f"--video-dir 中没有找到 {video_stem(page)}.*")
    return cached


def frame_points(pages: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if not pages:
        return []
    durations = [max(1.0, float(page.get("duration") or 0)) for page in pages]
    total = sum(durations)
    absolute_points: list[float] = []
    if count >= len(pages):
        offset = 0.0
        for duration in durations:
            absolute_points.append(offset + duration * 0.5)
            offset += duration
        extra_count = count - len(pages)
        for index in range(extra_count):
            ratio = 0.5 if extra_count == 1 else index / (extra_count - 1)
            absolute_points.append(total * (0.02 + 0.96 * ratio))
        absolute_points.sort()
    else:
        for index in range(count):
            ratio = 0.5 if count == 1 else index / (count - 1)
            absolute_points.append(total * (0.02 + 0.96 * ratio))

    points: list[dict[str, Any]] = []
    for absolute in absolute_points:
        offset = 0.0
        selected_page = pages[-1]
        local_time = durations[-1]
        for page, duration in zip(pages, durations):
            if absolute <= offset + duration:
                selected_page = page
                local_time = max(0.0, min(duration, absolute - offset))
                break
            offset += duration
        points.append(
            {
                "page": int(selected_page.get("page") or 1),
                "cid": selected_page.get("cid"),
                "part": selected_page.get("part") or "",
                "timestamp_seconds": round(local_time, 3),
                "timestamp": format_clock(local_time),
            }
        )
    return points


def extract_frame(video: Path, timestamp: float, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={FRAME_WIDTH}:{FRAME_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={FRAME_WIDTH}:{FRAME_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=white"
    )
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
        "-ss",
        str(max(0.0, timestamp)),
        "-frames:v",
        "1",
        "-vf",
        vf,
        str(output),
    ]
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("抽取关键帧需要 ffmpeg") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"无法从 {video.name} 的 {format_clock(timestamp)} 抽取画面") from exc
    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError(f"视频在 {format_clock(timestamp)} 没有输出画面")


def create_contact_sheet(frame_dir: Path, frame_count: int, output: Path) -> None:
    vf = (
        f"scale={CELL_WIDTH}:{CELL_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={CELL_WIDTH}:{CELL_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=white,"
        f"tile={GRID_COLUMNS}x{GRID_ROWS}:padding=4:margin=4:color=white"
    )
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-framerate",
        "1",
        "-start_number",
        "1",
        "-i",
        str(frame_dir / "frame_%03d.png"),
        "-frames:v",
        "1",
        "-vf",
        vf,
        str(output),
    ]
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("生成关键帧联系图需要 ffmpeg") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"无法生成关键帧联系图（已有 {frame_count} 张帧）") from exc


def write_keyframe_readme(keyframe_dir: Path, manifest: dict[str, Any]) -> None:
    sheet_name = Path(str(manifest["sheet"])).name
    lines = [
        "# 关键帧索引",
        "",
        f"联系图：`{sheet_name}`（{GRID_COLUMNS} 列 × {GRID_ROWS} 行，按行阅读）",
        "",
        "先看联系图；只有文字、代码或图表看不清时，再打开对应单帧。",
        "",
        "| 编号 | 分P | 时间 | 单帧 |",
        "| --- | ---: | ---: | --- |",
    ]
    for item in manifest["frames"]:
        frame_path = Path(str(item["file"]))
        frame_link = Path(*frame_path.parts[1:]) if frame_path.parts and frame_path.parts[0] == "keyframes" else frame_path
        lines.append(
            f"| `{item['evidence_id']}` | P{item['page']:02d} | {item['timestamp']} | "
            f"[{frame_path.name}]({frame_link.as_posix()}) |"
        )
    (keyframe_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.count < 1 or args.count > GRID_COLUMNS * GRID_ROWS:
        raise ValueError(f"--count 必须在 1 到 {GRID_COLUMNS * GRID_ROWS} 之间")

    bvid = extract_bvid(args.source)
    view = api_get("/x/web-interface/view", {"bvid": bvid}, bvid)
    pages = select_pages((view.get("data") or {}).get("pages") or [], args.parts)
    if not pages:
        raise RuntimeError("没有选中可抽帧的分P")

    out_dir = Path(args.out).resolve()
    keyframe_dir = out_dir / "keyframes"
    video_dir = out_dir / "video"
    frame_dir = keyframe_dir / "frames"
    keyframe_dir.mkdir(parents=True, exist_ok=True)
    frame_dir.mkdir(parents=True, exist_ok=True)

    previous_manifest_path = out_dir / "keyframes_manifest.json"
    previous_count = None
    if previous_manifest_path.exists():
        try:
            previous_count = int(json.loads(previous_manifest_path.read_text(encoding="utf-8")).get("frame_count"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            previous_count = None
    if args.force or (previous_count is not None and previous_count != args.count):
        for stale_frame in frame_dir.glob("frame_*.png"):
            stale_frame.unlink()

    points = frame_points(pages, args.count)
    page_by_key = {(str(page.get("page")), str(page.get("cid"))): page for page in pages}
    videos: dict[tuple[str, str], tuple[Path, str]] = {}
    for point in points:
        key = (str(point["page"]), str(point["cid"]))
        if key in videos:
            continue
        page = page_by_key[key]
        if args.video_dir:
            videos[key] = (local_video(Path(args.video_dir), page), "local")
        else:
            videos[key] = resolve_video(
                bvid,
                page,
                video_dir,
                args.video_source,
                args.cookies_from_browser,
                args.force,
            )

    frames: list[dict[str, Any]] = []
    frames_changed = False
    for index, point in enumerate(points, 1):
        key = (str(point["page"]), str(point["cid"]))
        video, source = videos[key]
        frame_path = frame_dir / f"frame_{index:03d}.png"
        if args.force or not frame_path.exists():
            extract_frame(video, point["timestamp_seconds"], frame_path)
            frames_changed = True
        frames.append(
            {
                "evidence_id": f"KF-P{point['page']:02d}-{index:02d}",
                "page": point["page"],
                "cid": point["cid"],
                "part": point["part"],
                "timestamp_seconds": point["timestamp_seconds"],
                "timestamp": point["timestamp"],
                "sheet_cell": {"row": (index - 1) // GRID_COLUMNS + 1, "column": (index - 1) % GRID_COLUMNS + 1},
                "file": f"keyframes/frames/frame_{index:03d}.png",
                "video_source": source,
            }
        )

    sheet_path = keyframe_dir / "contact_sheet.png"
    if args.force or frames_changed or not sheet_path.exists():
        create_contact_sheet(frame_dir, len(frames), sheet_path)

    manifest = {
        "status": "ok",
        "source": args.source,
        "bvid": bvid,
        "parts": args.parts,
        "selected_parts": [{"page": page.get("page"), "cid": page.get("cid"), "part": page.get("part") or ""} for page in pages],
        "requested_video_source": "local" if args.video_dir else args.video_source,
        "frame_count": len(frames),
        "grid": {"columns": GRID_COLUMNS, "rows": GRID_ROWS},
        "sheet": "keyframes/contact_sheet.png",
        "frames": frames,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "keyframes_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_keyframe_readme(keyframe_dir, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Bilibili video URL or BVID")
    parser.add_argument("--out", required=True, help="Extraction output directory")
    parser.add_argument("--parts", default="all", help="'all', 'key', or comma-separated page numbers")
    parser.add_argument("--count", type=int, default=12, help="Number of representative frames (1-12)")
    parser.add_argument(
        "--video-source",
        choices=["auto", "bilibili-api", "yt-dlp"],
        default="auto",
        help="Video source; auto tries the public Bilibili stream before yt-dlp",
    )
    parser.add_argument("--video-dir", help="Use existing per-part videos from this directory")
    parser.add_argument("--cookies-from-browser", help="Browser name for yt-dlp cookies, e.g. chrome or edge")
    parser.add_argument("--force", action="store_true", help="Re-download and re-extract existing keyframes")
    args = parser.parse_args()

    try:
        manifest = run(args)
    except (RuntimeError, ValueError) as exc:
        print(f"关键帧抽取失败：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
