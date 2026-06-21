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


def test_score_note_counts_opus_evidence_and_content_chars(tmp_path):
    module = load_module()
    archive_dir = tmp_path / "archive"
    note_path = tmp_path / "opus_note.md"
    budget_path = archive_dir / "metadata" / "note_budget.json"
    budget_path.parent.mkdir(parents=True)
    budget_path.write_text(
        json.dumps(
            {
                "content_type": "opus",
                "content_chars": 20000,
                "reading_minutes_estimate": 40,
                "all_evidence_blocks": 10,
                "recommended_note_chars_min": 100,
                "recommended_note_chars_max": 500,
                "base_note_chars_min": 90,
                "base_note_chars_max": 700,
                "quality_multiplier": 1.0,
                "quality_metrics": {"quality_tier": "medium"},
                "target_compression_ratio_min": 0.01,
                "target_compression_ratio_max": 0.03,
                "granularity": "long_article",
                "writing_guidance": "保留文章结构。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    note_path.write_text(
        "# 图文\n\n"
        + "这是图文笔记。" * 20
        + "\n\n证据：O123-E001、O123-E002、C123456。",
        encoding="utf-8",
    )

    result = module.score_note(archive_dir, note_path)

    assert result["actual_compression_ratio"] > 0
    assert result["note_chars_per_reading_minute"] > 0
    assert result["note_chars_per_minute"] is None
    assert result["evidence_refs_in_note"] == 3


def test_count_evidence_refs_reads_numbered_reference_links():
    module = load_module()
    markdown = (
        "关键判断用论文式编号。[1][2][3]\n\n"
        "1. [图文证据 E006](原始材料/O123_标题/indexes/图文证据索引.md#O123-E006)\n"
        "2. [字幕 P01](原始材料/BV123_标题/indexes/字幕证据索引.md#P01@00:00:00-00:00:20)\n"
        "3. [评论 C123456](原始材料/BV123_标题/comments/评论全集.md)\n"
        "\n"
        "[1]: 原始材料/O123_标题/indexes/图文证据索引.md#O123-E006 \"图文证据 E006\"\n"
        "[2]: 原始材料/BV123_标题/indexes/字幕证据索引.md#P01@00:00:00-00:00:20 \"字幕 P01\"\n"
        "[3]: 原始材料/BV123_标题/comments/评论全集.md \"评论 C123456\"\n"
    )

    assert module.count_evidence_refs(markdown) == 3


def test_visible_text_chars_ignores_reference_link_definitions():
    module = load_module()
    markdown = (
        "# 标题\n\n"
        "正文需要计数。[1]\n\n"
        "[1]: 原始材料/O123_标题/indexes/图文证据索引.md#O123-E006 \"图文证据 E006\"\n"
    )

    assert module.visible_text_chars(markdown) == len("标题正文需要计数。[1]")


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


def test_update_note_budget_section_uses_opus_wording(tmp_path):
    module = load_update_module()
    archive_dir = tmp_path / "archive"
    note_path = tmp_path / "opus_note.md"
    budget_path = archive_dir / "metadata" / "note_budget.json"
    budget_path.parent.mkdir(parents=True)
    budget_path.write_text(
        json.dumps(
            {
                "content_type": "opus",
                "content_chars": 20000,
                "reading_minutes_estimate": 40,
                "article_blocks": 200,
                "all_evidence_blocks": 20,
                "base_note_chars_min": 1000,
                "base_note_chars_max": 2000,
                "quality_multiplier": 1.0,
                "quality_metrics": {"like": 10, "favorite": 5, "reply": 1},
                "recommended_note_chars_min": 100,
                "recommended_note_chars_max": 300,
                "granularity": "long_article",
                "writing_guidance": "保留文章结构。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    note_path.write_text("# 图文\n\n## 核心观点\n\n正文 O123-E001。", encoding="utf-8")

    score = module.update_note(note_path, archive_dir)

    text = note_path.read_text(encoding="utf-8")
    assert "图文正文" in text
    assert "每阅读分钟笔记" in text
    assert "当前/图文正文压缩比" in text
    assert score["evidence_refs_in_note"] == 1
