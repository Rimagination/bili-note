import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "score_bili_note.py"
UPDATE_SCRIPT = ROOT / "scripts" / "update_note_budget_section.py"


def load_module():
    spec = importlib.util.spec_from_file_location("score_bili_note", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_update_module():
    spec = importlib.util.spec_from_file_location("update_note_budget_section", UPDATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_score_note_against_budget(tmp_path):
    module = load_module()
    archive_dir = tmp_path / "archive"
    note_path = tmp_path / "note.md"
    budget_path = archive_dir / "metadata" / "note_budget.json"
    budget_path.parent.mkdir(parents=True)
    budget_path.write_text(
        json.dumps(
            {
                "duration_minutes": 10,
                "subtitle_chars": 10000,
                "all_evidence_blocks": 20,
                "recommended_note_chars_min": 100,
                "recommended_note_chars_max": 300,
                "base_note_chars_min": 90,
                "base_note_chars_max": 270,
                "quality_multiplier": 1.1,
                "quality_metrics": {"quality_tier": "high"},
                "target_compression_ratio_min": 0.01,
                "target_compression_ratio_max": 0.03,
                "granularity": "short_video",
                "writing_guidance": "保留核心观点。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    note_path.write_text(
        "# 测试\n\n"
        "这是一个包含足够正文的测试笔记。" * 8
        + "\n\n证据：P01@00:00:00-00:00:20，C123456。",
        encoding="utf-8",
    )

    result = module.score_note(archive_dir, note_path)

    assert result["status"] == "ok"
    assert result["actual_compression_ratio"] > 0
    assert result["note_chars_per_minute"] > 0
    assert result["evidence_refs_in_note"] == 2
    assert result["quality_multiplier"] == 1.1
    assert result["quality_metrics"]["quality_tier"] == "high"


def test_update_note_budget_section_writes_markdown_and_score(tmp_path):
    module = load_update_module()
    archive_dir = tmp_path / "archive"
    note_path = tmp_path / "note.md"
    budget_path = archive_dir / "metadata" / "note_budget.json"
    budget_path.parent.mkdir(parents=True)
    budget_path.write_text(
        json.dumps(
            {
                "duration_minutes": 10,
                "subtitle_chars": 10000,
                "all_evidence_blocks": 20,
                "base_note_chars_min": 90,
                "base_note_chars_max": 270,
                "quality_multiplier": 1.1,
                "quality_metrics": {
                    "view": 1000,
                    "like": 50,
                    "favorite": 30,
                    "coin": 10,
                    "reply": 5,
                    "danmaku": 3,
                    "share": 2,
                    "published_at": "2025-01-01",
                    "days_since_publish": 30,
                },
                "recommended_note_chars_min": 100,
                "recommended_note_chars_max": 300,
                "granularity": "short_video",
                "writing_guidance": "保留核心观点。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    note_path.write_text("# 测试\n\n## 覆盖情况\n\n已覆盖。\n\n## 核心观点\n\n正文。", encoding="utf-8")

    score = module.update_note(note_path, archive_dir)

    text = note_path.read_text(encoding="utf-8")
    assert "## 笔记预算与信噪比" in text
    assert "质量倍率 1.100" in text
    assert (archive_dir / "metadata" / "note_score.json").exists()
    assert score["quality_multiplier"] == 1.1
