"""Archive Bilibili extraction outputs for long-term knowledge-base use.

Input is an extraction directory created by extract_bilibili.py and optionally
fetch_browser_ai_subtitles.py/download_browser_subtitles.py. The script copies
raw subtitles/comments into a stable archive and builds retrieval-friendly
Markdown and JSONL indexes.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def jsonl_line(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def format_clock(seconds: Any) -> str:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        value = 0.0
    total = int(value)
    hh, rem = divmod(total, 3600)
    mm, ss = divmod(rem, 60)
    return f"{hh:02}:{mm:02}:{ss:02}"


def clean_filename(value: str, limit: int = 90) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    return (value[:limit] or "untitled").strip(" ._")


def clamp(value: float, low: int, high: int) -> int:
    return int(max(low, min(high, round(value))))


def clamp_float(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def find_subtitle_manifest(extract_dir: Path) -> Path | None:
    for name in (
        "browser_ai_subtitle_manifest.json",
        "browser_subtitle_manifest.json",
        "subtitle_manifest.json",
    ):
        path = extract_dir / name
        if path.exists() and path.stat().st_size > 2:
            return path
    return None


def existing_subtitle_summary(archive_dir: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    outputs = manifest.get("outputs") or []
    duration_seconds = float(manifest.get("duration_seconds") or 0)
    subtitle_lines = int(manifest.get("subtitle_lines") or 0)
    subtitle_chars = int(manifest.get("subtitle_chars") or 0)
    evidence_blocks = int(manifest.get("evidence_blocks") or 0)

    if not duration_seconds:
        for item in outputs:
            try:
                duration_seconds += float(item.get("duration") or 0)
            except (TypeError, ValueError):
                pass

    if not subtitle_lines:
        subtitle_lines = sum(int(item.get("line_count") or 0) for item in outputs)

    if not subtitle_chars:
        for item in outputs:
            json_value = item.get("json")
            txt_value = item.get("txt")
            json_path = Path(json_value) if json_value else None
            txt_path = Path(txt_value) if txt_value else None
            if json_path and not json_path.is_absolute():
                json_path = archive_dir / json_path
            if txt_path and not txt_path.is_absolute():
                txt_path = archive_dir / txt_path
            if json_path and json_path.exists():
                payload = read_json(json_path)
                for seg in payload.get("body") or []:
                    subtitle_chars += len(str(seg.get("content") or "").strip())
            elif txt_path and txt_path.exists():
                for line in txt_path.read_text(encoding="utf-8").splitlines():
                    subtitle_chars += len(line.strip())

    if not evidence_blocks:
        evidence_path = archive_dir / "indexes" / "字幕证据索引.jsonl"
        if evidence_path.exists():
            evidence_blocks = len([line for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()])

    duration_minutes = round(duration_seconds / 60, 3) if duration_seconds else 0
    subtitle_chars_per_minute = round(subtitle_chars / (duration_seconds / 60), 3) if duration_seconds else None
    summary = {
        "available": True,
        "from_existing_archive": True,
        "parts": int(manifest.get("parts") or len(outputs)),
        "duration_seconds": round(duration_seconds, 3),
        "duration_minutes": duration_minutes,
        "subtitle_lines": subtitle_lines,
        "subtitle_chars": subtitle_chars,
        "subtitle_chars_per_minute": subtitle_chars_per_minute,
        "evidence_blocks": evidence_blocks,
    }

    manifest.update({key: value for key, value in summary.items() if key not in {"available", "from_existing_archive"}})
    write_json(manifest_path, manifest)
    return summary


def archive_subtitles(extract_dir: Path, archive_dir: Path) -> dict[str, Any]:
    manifest_path = find_subtitle_manifest(extract_dir)
    if not manifest_path:
        existing_manifest = archive_dir / "metadata" / "subtitles_manifest.clean.json"
        if existing_manifest.exists():
            return existing_subtitle_summary(archive_dir, existing_manifest)
        return {"available": False, "reason": "no subtitle manifest found"}

    manifest = read_json(manifest_path)
    if isinstance(manifest, list):
        outputs = manifest
    elif isinstance(manifest, dict):
        outputs = manifest.get("outputs") or []
    else:
        outputs = []

    txt_dir = archive_dir / "subtitles" / "txt"
    srt_dir = archive_dir / "subtitles" / "srt"
    json_dir = archive_dir / "subtitles" / "json"
    index_dir = archive_dir / "indexes"

    all_md: list[str] = ["# 字幕全集", ""]
    all_jsonl: list[str] = []
    evidence_jsonl: list[str] = []
    evidence_md: list[str] = ["# 字幕证据索引", ""]
    clean_outputs: list[dict[str, Any]] = []
    total_lines = 0
    total_chars = 0
    total_duration_seconds = 0.0

    def flush_evidence(
        page: int,
        cid: Any,
        part: str,
        start: Any,
        end: Any,
        lines: list[str],
        evidence_no: int,
    ) -> int:
        if not lines:
            return evidence_no
        evidence_no += 1
        start_label = format_clock(start)
        end_label = format_clock(end)
        evidence_id = f"P{page:02d}@{start_label}-{end_label}"
        text = "\n".join(lines).strip()
        record = {
            "type": "subtitle_evidence",
            "evidence_id": evidence_id,
            "page": page,
            "part": part,
            "cid": cid,
            "start": start,
            "end": end,
            "start_label": start_label,
            "end_label": end_label,
            "text": text,
        }
        evidence_jsonl.append(jsonl_line(record))
        evidence_md.extend([f"## {evidence_id} {part}", "", text, ""])
        return evidence_no

    for item in outputs:
        files = item.get("files") or {}
        page = int(item.get("page") or 0)
        cid = item.get("cid")
        part = item.get("part") or f"P{page:02d}"
        duration = item.get("duration")
        try:
            total_duration_seconds += float(duration or 0)
        except (TypeError, ValueError):
            pass
        stem = f"p{page:02d}_{cid}_{clean_filename(part, 40)}"

        src_txt = Path(files.get("txt", ""))
        src_srt = Path(files.get("srt", ""))
        src_json = Path(files.get("json", ""))
        dst_txt = txt_dir / f"{stem}.txt"
        dst_srt = srt_dir / f"{stem}.srt"
        dst_json = json_dir / f"{stem}.subtitle.json"

        copied_txt = copy_if_exists(src_txt, dst_txt)
        copied_srt = copy_if_exists(src_srt, dst_srt)
        copied_json = copy_if_exists(src_json, dst_json)

        all_md.extend([f"## P{page:02d} {part}", "", f"- CID: {cid}", f"- Duration: {duration}s", ""])

        line_count = 0
        chunk_lines: list[str] = []
        chunk_start: Any = None
        chunk_end: Any = None
        chunk_chars = 0
        evidence_no = 0
        if copied_json:
            payload = read_json(dst_json)
            for seg_idx, seg in enumerate(payload.get("body") or [], 1):
                content = str(seg.get("content", "")).strip()
                if not content:
                    continue
                if chunk_start is None:
                    chunk_start = seg.get("from")
                chunk_end = seg.get("to")
                chunk_lines.append(content)
                chunk_chars += len(content)
                total_chars += len(content)
                record = {
                    "type": "subtitle",
                    "page": page,
                    "part": part,
                    "cid": cid,
                    "segment": seg_idx,
                    "from": seg.get("from"),
                    "to": seg.get("to"),
                    "content": content,
                }
                all_jsonl.append(jsonl_line(record))
                all_md.append(f"[{seg.get('from', '')}-{seg.get('to', '')}] {content}")
                line_count += 1
                if chunk_chars >= 550 or len(chunk_lines) >= 14:
                    evidence_no = flush_evidence(page, cid, part, chunk_start, chunk_end, chunk_lines, evidence_no)
                    chunk_lines = []
                    chunk_start = None
                    chunk_end = None
                    chunk_chars = 0
            evidence_no = flush_evidence(page, cid, part, chunk_start, chunk_end, chunk_lines, evidence_no)
        elif copied_txt:
            for seg_idx, content in enumerate(dst_txt.read_text(encoding="utf-8").splitlines(), 1):
                content = content.strip()
                if not content:
                    continue
                if chunk_start is None:
                    chunk_start = seg_idx
                chunk_end = seg_idx
                chunk_lines.append(content)
                chunk_chars += len(content)
                total_chars += len(content)
                record = {
                    "type": "subtitle",
                    "page": page,
                    "part": part,
                    "cid": cid,
                    "segment": seg_idx,
                    "from": None,
                    "to": None,
                    "content": content,
                }
                all_jsonl.append(jsonl_line(record))
                all_md.append(content)
                line_count += 1
                if chunk_chars >= 550 or len(chunk_lines) >= 14:
                    evidence_no = flush_evidence(page, cid, part, chunk_start, chunk_end, chunk_lines, evidence_no)
                    chunk_lines = []
                    chunk_start = None
                    chunk_end = None
                    chunk_chars = 0
            evidence_no = flush_evidence(page, cid, part, chunk_start, chunk_end, chunk_lines, evidence_no)

        total_lines += line_count
        all_md.append("")
        clean_outputs.append(
            {
                "page": page,
                "cid": cid,
                "part": part,
                "duration": duration,
                "line_count": line_count,
                "txt": str(dst_txt) if copied_txt else None,
                "srt": str(dst_srt) if copied_srt else None,
                "json": str(dst_json) if copied_json else None,
            }
        )

    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "字幕全集.md").write_text("\n".join(all_md), encoding="utf-8")
    (index_dir / "字幕全集.jsonl").write_text("\n".join(all_jsonl) + ("\n" if all_jsonl else ""), encoding="utf-8")
    (index_dir / "字幕证据索引.md").write_text("\n".join(evidence_md), encoding="utf-8")
    (index_dir / "字幕证据索引.jsonl").write_text("\n".join(evidence_jsonl) + ("\n" if evidence_jsonl else ""), encoding="utf-8")

    clean_manifest = {
        "source_manifest": manifest_path.name,
        "bvid": manifest.get("bvid"),
        "aid": manifest.get("aid"),
        "parts": len(clean_outputs),
        "duration_seconds": round(total_duration_seconds, 3),
        "duration_minutes": round(total_duration_seconds / 60, 3) if total_duration_seconds else 0,
        "subtitle_lines": total_lines,
        "subtitle_chars": total_chars,
        "subtitle_chars_per_minute": round(total_chars / (total_duration_seconds / 60), 3) if total_duration_seconds else None,
        "evidence_blocks": len(evidence_jsonl),
        "outputs": clean_outputs,
    }
    write_json(archive_dir / "metadata" / "subtitles_manifest.clean.json", clean_manifest)
    return {
        "available": True,
        "parts": len(clean_outputs),
        "duration_seconds": round(total_duration_seconds, 3),
        "duration_minutes": round(total_duration_seconds / 60, 3) if total_duration_seconds else 0,
        "subtitle_lines": total_lines,
        "subtitle_chars": total_chars,
        "subtitle_chars_per_minute": round(total_chars / (total_duration_seconds / 60), 3) if total_duration_seconds else None,
        "evidence_blocks": len(evidence_jsonl),
    }


def flatten_comments(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in items:
        base = {
            "type": "comment",
            "level": 1,
            "rpid": item.get("rpid"),
            "root": item.get("root"),
            "parent": item.get("parent"),
            "uname": item.get("uname"),
            "mid": item.get("mid"),
            "time": item.get("time"),
            "ctime": item.get("ctime"),
            "like": item.get("like"),
            "message": item.get("message"),
            "pictures": item.get("pictures"),
            "links": item.get("links"),
            "up_liked": item.get("up_liked"),
            "up_replied": item.get("up_replied"),
        }
        records.append(base)
        for child in item.get("children") or []:
            records.append(
                {
                    "type": "comment",
                    "level": 2,
                    "rpid": child.get("rpid"),
                    "root": child.get("root"),
                    "parent": child.get("parent"),
                    "uname": child.get("uname"),
                    "mid": child.get("mid"),
                    "time": child.get("time"),
                    "ctime": child.get("ctime"),
                    "like": child.get("like"),
                    "message": child.get("message"),
                    "pictures": child.get("pictures"),
                    "links": child.get("links"),
                    "up_liked": child.get("up_liked"),
                    "up_replied": child.get("up_replied"),
                    "parent_reply_member": child.get("parent_reply_member"),
                }
            )
    return records


def archive_comments(extract_dir: Path, archive_dir: Path) -> dict[str, Any]:
    raw_path = extract_dir / "comments_raw.json"
    md_path = extract_dir / "comments.md"
    if not raw_path.exists():
        return {"available": False, "reason": "comments_raw.json not found"}

    comments_dir = archive_dir / "comments"
    index_dir = archive_dir / "indexes"
    copy_if_exists(raw_path, comments_dir / "comments_raw.json")
    copy_if_exists(md_path, comments_dir / "评论全集.md")

    raw = read_json(raw_path)
    records = flatten_comments(raw.get("items") or [])
    jsonl = "\n".join(jsonl_line(record) for record in records)
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "评论全集.jsonl").write_text(jsonl + ("\n" if jsonl else ""), encoding="utf-8")
    evidence_records = []
    for record in records:
        message = str(record.get("message") or "").strip()
        if not message:
            continue
        evidence_records.append(
            {
                "type": "comment_evidence",
                "evidence_id": f"C{record.get('rpid')}",
                "level": record.get("level"),
                "rpid": record.get("rpid"),
                "root": record.get("root"),
                "parent": record.get("parent"),
                "uname": record.get("uname"),
                "time": record.get("time"),
                "like": record.get("like"),
                "text": message,
            }
        )
    (index_dir / "评论证据索引.jsonl").write_text(
        "\n".join(jsonl_line(record) for record in evidence_records) + ("\n" if evidence_records else ""),
        encoding="utf-8",
    )

    summary = {
        "source": raw.get("source"),
        "aid": raw.get("aid"),
        "bvid": raw.get("bvid"),
        "fetched_at": raw.get("fetched_at"),
        "wbi_main_all_count": raw.get("wbi_main_all_count"),
        "top_level_count": raw.get("top_level_count"),
        "child_reply_count": raw.get("child_reply_count"),
        "total_fetched_comments": raw.get("total_fetched_comments"),
        "jsonl_records": len(records),
        "evidence_blocks": len(evidence_records),
    }
    write_json(archive_dir / "metadata" / "comments_manifest.clean.json", summary)
    return {"available": True, **summary}


def combine_evidence_indexes(archive_dir: Path) -> int:
    index_dir = archive_dir / "indexes"
    sources = [index_dir / "字幕证据索引.jsonl", index_dir / "评论证据索引.jsonl"]
    lines: list[str] = []
    for source in sources:
        if source.exists():
            lines.extend([line for line in source.read_text(encoding="utf-8").splitlines() if line.strip()])
    (index_dir / "证据索引.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)


def normalized_log_score(value: float, reference: float) -> float:
    if value <= 0 or reference <= 0:
        return 0.0
    return clamp_float(math.log1p(value) / math.log1p(reference), 0.0, 1.0)


def extract_quality_metrics(archive_dir: Path, now: datetime | None = None) -> dict[str, Any]:
    metadata_path = archive_dir / "metadata" / "metadata.json"
    if not metadata_path.exists():
        return {
            "available": False,
            "quality_score": 0.273,
            "quality_multiplier": 1.0,
            "reason": "metadata.json not found",
        }

    payload = read_json(metadata_path)
    data = payload.get("data") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    stat = data.get("stat") or {}
    if not isinstance(stat, dict):
        stat = {}

    view = as_int(stat.get("view"))
    danmaku = as_int(stat.get("danmaku"))
    reply = as_int(stat.get("reply"))
    favorite = as_int(stat.get("favorite"))
    coin = as_int(stat.get("coin"))
    share = as_int(stat.get("share"))
    like = as_int(stat.get("like"))
    pubdate = as_int(data.get("pubdate"))

    now = now or datetime.now(timezone.utc)
    published_at = None
    days_since_publish = None
    if pubdate > 0:
        published_at_dt = datetime.fromtimestamp(pubdate, tz=timezone.utc)
        published_at = published_at_dt.date().isoformat()
        days_since_publish = max(0, (now.date() - published_at_dt.date()).days)
    age_days = max(days_since_publish or 0, 1)

    weighted_engagement = like + favorite * 1.4 + coin * 2.2 + reply * 1.8 + danmaku * 0.8 + share * 1.5
    engagement_rate = weighted_engagement / view if view else 0.0
    favorite_rate = favorite / view if view else 0.0
    discussion_rate = (reply + danmaku) / view if view else 0.0
    view_per_day = view / age_days if pubdate else 0.0
    engagement_per_day = weighted_engagement / age_days if pubdate else 0.0

    engagement_rate_score = normalized_log_score(engagement_rate * 1000, 80)
    favorite_rate_score = normalized_log_score(favorite_rate * 1000, 50)
    discussion_score = normalized_log_score(discussion_rate * 1000, 20)
    view_velocity_score = normalized_log_score(view_per_day, 10000)
    engagement_velocity_score = normalized_log_score(engagement_per_day, 1000)
    quality_score = (
        engagement_rate_score * 0.28
        + favorite_rate_score * 0.18
        + discussion_score * 0.12
        + view_velocity_score * 0.20
        + engagement_velocity_score * 0.22
    )
    quality_multiplier = clamp_float(0.85 + quality_score * 0.55, 0.85, 1.4)

    if quality_score >= 0.72:
        quality_tier = "high"
    elif quality_score >= 0.45:
        quality_tier = "medium"
    else:
        quality_tier = "low"

    return {
        "available": True,
        "published_at": published_at,
        "days_since_publish": days_since_publish,
        "view": view,
        "like": like,
        "favorite": favorite,
        "coin": coin,
        "reply": reply,
        "danmaku": danmaku,
        "share": share,
        "weighted_engagement": round(weighted_engagement, 3),
        "engagement_rate": round(engagement_rate, 6) if view else None,
        "favorite_rate": round(favorite_rate, 6) if view else None,
        "discussion_rate": round(discussion_rate, 6) if view else None,
        "view_per_day": round(view_per_day, 3) if pubdate else None,
        "weighted_engagement_per_day": round(engagement_per_day, 3) if pubdate else None,
        "engagement_rate_score": round(engagement_rate_score, 4),
        "favorite_rate_score": round(favorite_rate_score, 4),
        "discussion_score": round(discussion_score, 4),
        "view_velocity_score": round(view_velocity_score, 4),
        "engagement_velocity_score": round(engagement_velocity_score, 4),
        "quality_score": round(quality_score, 4),
        "quality_tier": quality_tier,
        "quality_multiplier": round(quality_multiplier, 3),
        "quality_basis": "点赞、收藏、投币、评论、弹幕、分享、播放量和发布时间距今天数的综合信号",
    }


def write_note_budget(archive_dir: Path, subtitle_info: dict[str, Any], comment_info: dict[str, Any], evidence_count: int) -> dict[str, Any]:
    duration_minutes = float(subtitle_info.get("duration_minutes") or 0)
    subtitle_chars = int(subtitle_info.get("subtitle_chars") or 0)
    evidence_blocks = int(subtitle_info.get("evidence_blocks") or 0)
    comment_records = int(comment_info.get("jsonl_records") or comment_info.get("total_fetched_comments") or 0)
    parts = int(subtitle_info.get("parts") or 0)
    quality_metrics = extract_quality_metrics(archive_dir)
    quality_multiplier = float(quality_metrics.get("quality_multiplier") or 1.0)

    # Scale with information volume while keeping very long courses manageable.
    base_target_min = clamp(
        600 + duration_minutes * 35 + subtitle_chars * 0.025 + evidence_blocks * 8 + min(comment_records, 300) * 3,
        1200,
        45000,
    )
    base_target_max = clamp(base_target_min * 1.45, 1800, 65000)
    target_min = clamp(base_target_min * quality_multiplier, 1200, 65000)
    target_max = clamp(target_min * 1.45, 1800, 65000)
    quick_target = clamp(target_min * 0.45, 800, 12000)
    deep_target = clamp(target_max * 1.6, target_max, 110000)

    subtitle_chars_per_minute = subtitle_info.get("subtitle_chars_per_minute")
    evidence_blocks_per_minute = round(evidence_blocks / duration_minutes, 3) if duration_minutes else None
    compression_ratio_min = round(target_min / subtitle_chars, 4) if subtitle_chars else None
    compression_ratio_max = round(target_max / subtitle_chars, 4) if subtitle_chars else None

    if duration_minutes >= 120 or parts >= 10:
        granularity = "long_course"
        writing_guidance = "按模块/分P写，保留逐P表；不要压成短视频式摘要。"
    elif duration_minutes >= 25:
        granularity = "medium_deep_dive"
        writing_guidance = "保留章节结构、关键论点、方法步骤和代表证据。"
    else:
        granularity = "short_video"
        writing_guidance = "以核心观点、证据和少量实践建议为主，避免过度扩写。"

    budget = {
        "duration_minutes": round(duration_minutes, 3),
        "parts": parts,
        "subtitle_lines": subtitle_info.get("subtitle_lines"),
        "subtitle_chars": subtitle_chars,
        "subtitle_chars_per_minute": subtitle_chars_per_minute,
        "subtitle_evidence_blocks": evidence_blocks,
        "comment_records": comment_records,
        "all_evidence_blocks": evidence_count,
        "evidence_blocks_per_minute": evidence_blocks_per_minute,
        "base_note_chars_min": base_target_min,
        "base_note_chars_max": base_target_max,
        "quality_multiplier": round(quality_multiplier, 3),
        "quality_metrics": quality_metrics,
        "recommended_note_chars_min": target_min,
        "recommended_note_chars_max": target_max,
        "quick_note_chars": quick_target,
        "deep_note_chars": deep_target,
        "target_compression_ratio_min": compression_ratio_min,
        "target_compression_ratio_max": compression_ratio_max,
        "granularity": granularity,
        "writing_guidance": writing_guidance,
    }
    write_json(archive_dir / "metadata" / "note_budget.json", budget)
    return budget


def archive_metadata(extract_dir: Path, archive_dir: Path) -> dict[str, bool]:
    copied: dict[str, bool] = {}
    for name in ("metadata.json", "source.md", "run_summary.json", "subtitle_probe.json"):
        copied[name] = copy_if_exists(extract_dir / name, archive_dir / "metadata" / name)
    return copied


def fmt_readme_number(value: Any) -> str:
    if value is None:
        return "未知"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def fmt_readme_float(value: Any, digits: int = 1) -> str:
    if value is None:
        return "未知"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def summarize_subtitles_for_readme(subtitle_info: dict[str, Any]) -> str:
    if not subtitle_info.get("available"):
        return f"未归档字幕（{subtitle_info.get('reason', '没有可用字幕')}）。"
    source = "；使用已有归档重建统计" if subtitle_info.get("from_existing_archive") else ""
    return (
        f"已归档 {fmt_readme_number(subtitle_info.get('parts'))} 个分P，"
        f"约 {fmt_readme_float(subtitle_info.get('duration_minutes'))} 分钟，"
        f"{fmt_readme_number(subtitle_info.get('subtitle_lines'))} 行字幕，"
        f"{fmt_readme_number(subtitle_info.get('subtitle_chars'))} 字，"
        f"{fmt_readme_number(subtitle_info.get('evidence_blocks'))} 个字幕证据块{source}。"
    )


def summarize_comments_for_readme(comment_info: dict[str, Any]) -> str:
    if not comment_info.get("available"):
        return f"未归档评论（{comment_info.get('reason', '没有抓取评论')}）。"
    shown_total = comment_info.get("wbi_main_all_count")
    shown_text = f"；B站接口显示约 {fmt_readme_number(shown_total)} 条" if shown_total is not None else ""
    return (
        f"已归档 {fmt_readme_number(comment_info.get('jsonl_records'))} 条评论/回复，"
        f"其中主评论 {fmt_readme_number(comment_info.get('top_level_count'))} 条，"
        f"子回复 {fmt_readme_number(comment_info.get('child_reply_count'))} 条，"
        f"生成 {fmt_readme_number(comment_info.get('evidence_blocks'))} 个评论证据块{shown_text}。"
    )


def summarize_metadata_for_readme(metadata_info: dict[str, bool]) -> str:
    copied = [name for name, ok in metadata_info.items() if ok]
    missing = [name for name, ok in metadata_info.items() if not ok]
    if copied and not missing:
        return "元数据、来源说明、运行摘要和字幕探测记录均已归档。"
    if copied:
        return f"已归档：{', '.join(copied)}；缺少：{', '.join(missing) or '无'}。"
    return "未找到可归档的元数据文件。"


def summarize_budget_for_readme(note_budget: dict[str, Any]) -> str:
    quality = note_budget.get("quality_metrics") or {}
    engagement = ""
    if quality.get("available"):
        engagement = (
            f"互动质量倍率 {fmt_readme_float(note_budget.get('quality_multiplier'), 3)}"
            f"（播放 {fmt_readme_number(quality.get('view'))}，"
            f"点赞 {fmt_readme_number(quality.get('like'))}，"
            f"收藏 {fmt_readme_number(quality.get('favorite'))}，"
            f"投币 {fmt_readme_number(quality.get('coin'))}，"
            f"评论 {fmt_readme_number(quality.get('reply'))}，"
            f"弹幕 {fmt_readme_number(quality.get('danmaku'))}，"
            f"分享 {fmt_readme_number(quality.get('share'))}；"
            f"发布于 {quality.get('published_at') or '未知'}，"
            f"距今 {fmt_readme_number(quality.get('days_since_publish'))} 天）。"
        )
    else:
        engagement = "未能读取互动质量，使用默认倍率。"
    return (
        f"推荐笔记长度 {fmt_readme_number(note_budget.get('recommended_note_chars_min'))}-"
        f"{fmt_readme_number(note_budget.get('recommended_note_chars_max'))} 字；"
        f"{engagement}{note_budget.get('writing_guidance')}"
    )


def write_readme(
    archive_dir: Path,
    subtitle_info: dict[str, Any],
    comment_info: dict[str, Any],
    metadata_info: dict[str, bool],
    note_budget: dict[str, Any],
) -> None:
    lines = [
        "# B站视频材料包",
        "",
        "这是一个视频的长期材料包。知识库笔记适合快速阅读；这里保存完整字幕、评论、元数据和证据索引，方便以后追问、核对原文或重新生成笔记。",
        "",
        "## 先看哪里",
        "",
        "- 想通读原文：打开 `indexes/字幕全集.md`。",
        "- 想核对某个观点：查 `indexes/证据索引.jsonl`，里面包含字幕证据和评论证据。",
        "- 想看评论区：打开 `comments/评论全集.md`。",
        "- 想判断笔记是否写得过短或过长：看 `metadata/note_budget.json` 和 `metadata/note_score.json`。",
        "- 想让工具检索或问答：优先使用 `indexes/*.jsonl`。",
        "",
        "## 本次覆盖",
        "",
        f"- 字幕：{summarize_subtitles_for_readme(subtitle_info)}",
        f"- 评论：{summarize_comments_for_readme(comment_info)}",
        f"- 元数据：{summarize_metadata_for_readme(metadata_info)}",
        f"- 笔记预算：{summarize_budget_for_readme(note_budget)}",
        "",
        "## 文件说明",
        "",
        "- `subtitles/txt/`：每个分P的纯文本字幕。",
        "- `subtitles/srt/`：每个分P的 SRT 字幕，带时间轴，适合回看定位。",
        "- `subtitles/json/`：B站字幕原始 JSON，适合程序复用。",
        "- `comments/comments_raw.json`：完整评论原始结构。",
        "- `comments/评论全集.md`：适合人工阅读的完整评论。",
        "- `indexes/字幕全集.md`：合并后的完整字幕。",
        "- `indexes/字幕全集.jsonl`：逐字幕片段索引，适合检索和问答。",
        "- `indexes/字幕证据索引.md`：按时间段合并的字幕证据块，适合人工核对。",
        "- `indexes/字幕证据索引.jsonl`：字幕证据块的机器可读版本。",
        "- `indexes/评论全集.jsonl`：逐评论/回复索引。",
        "- `indexes/评论证据索引.jsonl`：评论证据块。",
        "- `indexes/证据索引.jsonl`：字幕证据和评论证据的合并索引。",
        "- `metadata/metadata.json`：B站视频元数据，包括标题、UP、发布时间和互动数据。",
        "- `metadata/note_budget.json`：根据视频时长、字幕量、证据量和互动质量生成的推荐笔记长度。",
        "- `metadata/note_score.json`：最终笔记与推荐长度的对比结果；如果还没有生成，可忽略。",
        "",
        "## 推荐用法",
        "",
        "1. 先读知识库里的最终笔记，快速了解结论。",
        "2. 对某个判断不放心时，用笔记里的 `Pxx@时间段` 或 `C评论ID` 回到 `indexes/证据索引.jsonl` 查原文。",
        "3. 需要更细的追问时，把 `indexes/字幕全集.jsonl` 和 `indexes/评论全集.jsonl` 当作问答材料。",
        "4. 重新写笔记前先看 `metadata/note_budget.json`：长视频、高互动视频应该保留更多结构和证据，短视频则避免过度扩写。",
        "",
    ]
    (archive_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive Bilibili subtitles/comments beside a knowledge note")
    parser.add_argument("--extract-dir", required=True, help="Temporary extraction output directory")
    parser.add_argument("--archive-dir", required=True, help="Permanent archive directory")
    args = parser.parse_args()

    extract_dir = Path(args.extract_dir)
    archive_dir = Path(args.archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)

    metadata_info = archive_metadata(extract_dir, archive_dir)
    subtitle_info = archive_subtitles(extract_dir, archive_dir)
    comment_info = archive_comments(extract_dir, archive_dir)
    evidence_count = combine_evidence_indexes(archive_dir)
    note_budget = write_note_budget(archive_dir, subtitle_info, comment_info, evidence_count)
    write_readme(archive_dir, subtitle_info, comment_info, metadata_info, note_budget)

    print(
        json.dumps(
            {
                "archive_dir": str(archive_dir),
                "subtitles": subtitle_info,
                "comments": comment_info,
                "evidence_blocks": evidence_count,
                "note_budget": note_budget,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
