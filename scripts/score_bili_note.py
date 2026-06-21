"""Score a generated Bili Note against its archive note budget."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def visible_text_chars(markdown: str) -> int:
    text = re.sub(r"```.*?```", "", markdown, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^[#>\-\*\|\s:]+", "", text, flags=re.M)
    text = re.sub(r"\s+", "", text)
    return len(text)


def count_evidence_refs(markdown: str) -> int:
    opus_refs = re.findall(r"\bO\d+-E\d{3}\b", markdown)
    subtitle_refs = re.findall(r"P\d{2}@\d{2}:\d{2}:\d{2}-\d{2}:\d{2}:\d{2}", markdown)
    comment_refs = re.findall(r"\bC\d{6,}\b", markdown)
    return len(set(opus_refs)) + len(set(subtitle_refs)) + len(set(comment_refs))


def status_for(actual: int, low: int, high: int) -> str:
    if actual < low:
        return "too_short"
    if actual > high:
        return "too_long"
    return "ok"


def score_note(archive_dir: Path, note_path: Path) -> dict[str, Any]:
    budget_path = archive_dir / "metadata" / "note_budget.json"
    budget = read_json(budget_path)
    note = note_path.read_text(encoding="utf-8")
    actual_chars = visible_text_chars(note)
    low = int(budget.get("recommended_note_chars_min") or 0)
    high = int(budget.get("recommended_note_chars_max") or 0)
    subtitle_chars = int(budget.get("subtitle_chars") or 0)
    content_chars = int(budget.get("content_chars") or subtitle_chars or 0)
    duration_minutes = float(budget.get("duration_minutes") or 0)
    reading_minutes = float(budget.get("reading_minutes_estimate") or 0)
    evidence_total = int(budget.get("all_evidence_blocks") or 0)
    evidence_refs = count_evidence_refs(note)
    return {
        "note_path": str(note_path),
        "archive_dir": str(archive_dir),
        "actual_note_chars": actual_chars,
        "base_note_chars_min": budget.get("base_note_chars_min"),
        "base_note_chars_max": budget.get("base_note_chars_max"),
        "recommended_note_chars_min": low,
        "recommended_note_chars_max": high,
        "status": status_for(actual_chars, low, high),
        "quality_multiplier": budget.get("quality_multiplier"),
        "quality_metrics": budget.get("quality_metrics"),
        "actual_compression_ratio": round(actual_chars / content_chars, 4) if content_chars else None,
        "target_compression_ratio_min": budget.get("target_compression_ratio_min"),
        "target_compression_ratio_max": budget.get("target_compression_ratio_max"),
        "note_chars_per_minute": round(actual_chars / duration_minutes, 3) if duration_minutes else None,
        "note_chars_per_reading_minute": round(actual_chars / reading_minutes, 3) if reading_minutes else None,
        "subtitle_chars_per_minute": budget.get("subtitle_chars_per_minute"),
        "evidence_refs_in_note": evidence_refs,
        "all_evidence_blocks": evidence_total,
        "evidence_reference_ratio": round(evidence_refs / evidence_total, 4) if evidence_total else None,
        "granularity": budget.get("granularity"),
        "writing_guidance": budget.get("writing_guidance"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score Markdown note length and evidence coverage against note_budget.json")
    parser.add_argument("--archive-dir", required=True)
    parser.add_argument("--note-path", required=True)
    parser.add_argument("--out", help="Optional JSON output path")
    args = parser.parse_args()

    archive_dir = Path(args.archive_dir)
    note_path = Path(args.note_path)
    result = score_note(archive_dir, note_path)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
