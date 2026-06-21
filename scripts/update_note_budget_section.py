"""Insert or refresh the note budget section in a Markdown Bili Note."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from score_bili_note import score_note


SECTION_TITLE = "## 笔记预算与信噪比"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fmt_int(value: Any) -> str:
    if value is None:
        return "未知"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def fmt_float(value: Any, digits: int = 3) -> str:
    if value is None:
        return "未知"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def status_label(status: str | None) -> str:
    return {
        "too_short": "偏短",
        "too_long": "偏长",
        "ok": "合适",
    }.get(status or "", status or "未知")


def status_advice(status: str | None) -> str:
    return {
        "too_short": "建议补充章节/分P层面的观点、方法步骤和证据；高信息量或高互动视频不宜压成短摘要。",
        "too_long": "建议压缩重复解释，保留核心判断、关键证据和可执行结论；短视频不必展开成课程笔记。",
        "ok": "当前长度落在推荐区间，后续优先根据提问从原始字幕和评论索引追查细节。",
    }.get(status or "", "需要结合原始字幕和评论索引复核。")


def build_section(budget: dict[str, Any], score: dict[str, Any]) -> str:
    quality = budget.get("quality_metrics") or {}
    status = score.get("status")
    lines = [
        SECTION_TITLE,
        "",
        (
            f"- 信息量基准：视频 {fmt_float(budget.get('duration_minutes'), 1)} 分钟，"
            f"字幕 {fmt_int(budget.get('subtitle_chars'))} 字，"
            f"证据块 {fmt_int(budget.get('all_evidence_blocks'))}；"
            f"基准推荐 {fmt_int(budget.get('base_note_chars_min'))}-{fmt_int(budget.get('base_note_chars_max'))} 字。"
        ),
        (
            f"- 互动质量：播放 {fmt_int(quality.get('view'))}，点赞 {fmt_int(quality.get('like'))}，"
            f"收藏 {fmt_int(quality.get('favorite'))}，投币 {fmt_int(quality.get('coin'))}，"
            f"评论 {fmt_int(quality.get('reply'))}，弹幕 {fmt_int(quality.get('danmaku'))}，"
            f"分享 {fmt_int(quality.get('share'))}；发布于 {quality.get('published_at') or '未知'}，"
            f"距今 {fmt_int(quality.get('days_since_publish'))} 天；"
            f"质量倍率 {fmt_float(budget.get('quality_multiplier'), 3)}。"
        ),
        (
            f"- 推荐区间：{fmt_int(score.get('recommended_note_chars_min'))}-{fmt_int(score.get('recommended_note_chars_max'))} 字；"
            f"当前约 {fmt_int(score.get('actual_note_chars'))} 字，状态：{status_label(status)}。"
        ),
        (
            f"- 信噪比：当前/字幕压缩比 {fmt_float(score.get('actual_compression_ratio'), 4)}；"
            f"每分钟笔记 {fmt_float(score.get('note_chars_per_minute'), 1)} 字；"
            f"证据引用 {fmt_int(score.get('evidence_refs_in_note'))}/{fmt_int(score.get('all_evidence_blocks'))}。"
        ),
        f"- 调整建议：{status_advice(status)}热度只作为是否值得多写的辅助信号，不能替代内容证据。",
        "",
    ]
    return "\n".join(lines)


def replace_section(markdown: str, section: str) -> str:
    markdown = re.sub(r"\n## 笔记预算与信噪比\n.*?(?=\n## )", "\n", markdown, flags=re.S)
    updated = None
    for marker in ("\n## 证据与原文位置", "\n## 来源、覆盖与局限", "\n## 核心观点"):
        if marker in markdown:
            updated = markdown.replace(marker, "\n" + section + marker, 1)
            break
    if updated is None:
        updated = markdown.rstrip() + "\n\n" + section
    updated = re.sub(r"\n{3,}(## 笔记预算与信噪比)", r"\n\n\1", updated)
    updated = re.sub(r"\n{3,}(## 核心观点)", r"\n\n\1", updated)
    updated = re.sub(r"\n{3,}(## 证据与原文位置)", r"\n\n\1", updated)
    updated = re.sub(r"\n{3,}(## 来源、覆盖与局限)", r"\n\n\1", updated)
    return updated


def update_note(note_path: Path, archive_dir: Path, score_path: Path | None = None) -> dict[str, Any]:
    budget_path = archive_dir / "metadata" / "note_budget.json"
    score_path = score_path or archive_dir / "metadata" / "note_score.json"
    budget = read_json(budget_path)

    for _ in range(2):
        score = score_note(archive_dir, note_path)
        section = build_section(budget, score)
        text = note_path.read_text(encoding="utf-8")
        note_path.write_text(replace_section(text, section), encoding="utf-8")

    final_score = score_note(archive_dir, note_path)
    write_json(score_path, final_score)
    final_section = build_section(budget, final_score)
    text = note_path.read_text(encoding="utf-8")
    note_path.write_text(replace_section(text, final_section), encoding="utf-8")
    return final_score


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the note budget and signal-to-noise section in a Bili Note")
    parser.add_argument("--note-path", required=True)
    parser.add_argument("--archive-dir", required=True)
    parser.add_argument("--score-out", help="Optional score JSON path; defaults to archive metadata/note_score.json")
    args = parser.parse_args()

    score = update_note(
        Path(args.note_path),
        Path(args.archive_dir),
        Path(args.score_out) if args.score_out else None,
    )
    print(json.dumps(score, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
