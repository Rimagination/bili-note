import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "archive_bili_materials.py"


def load_module():
    spec = importlib.util.spec_from_file_location("archive_bili_materials", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_archive_builds_subtitle_and_comment_evidence_indexes(tmp_path):
    module = load_module()
    extract_dir = tmp_path / "extract"
    archive_dir = tmp_path / "archive"
    source_subtitle = extract_dir / "p01.subtitle.json"
    source_txt = extract_dir / "p01.txt"
    source_srt = extract_dir / "p01.srt"

    write_json(
        source_subtitle,
        {
            "body": [
                {"from": 0.0, "to": 1.0, "content": "第一句 RAG"},
                {"from": 1.0, "to": 2.0, "content": "第二句 检索"},
            ]
        },
    )
    source_txt.write_text("第一句 RAG\n第二句 检索\n", encoding="utf-8")
    source_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n第一句 RAG\n", encoding="utf-8")
    write_json(
        extract_dir / "browser_ai_subtitle_manifest.json",
        {
            "bvid": "BVtest",
            "aid": 123,
            "outputs": [
                {
                    "page": 1,
                    "cid": 456,
                    "part": "测试分P",
                    "duration": 2,
                    "files": {"json": str(source_subtitle), "txt": str(source_txt), "srt": str(source_srt)},
                }
            ],
        },
    )
    write_json(
        extract_dir / "comments_raw.json",
        {
            "source": "https://www.bilibili.com/video/BVtest/",
            "aid": "123",
            "bvid": "BVtest",
            "items": [
                {
                    "rpid": "1",
                    "root": "0",
                    "parent": "0",
                    "uname": "用户A",
                    "message": "这个分块方法有用",
                    "children": [
                        {
                            "rpid": "2",
                            "root": "1",
                            "parent": "1",
                            "uname": "用户B",
                            "message": "补充：要加 reranker",
                        }
                    ],
                }
            ],
        },
    )

    metadata_info = module.archive_metadata(extract_dir, archive_dir)
    subtitle_info = module.archive_subtitles(extract_dir, archive_dir)
    comment_info = module.archive_comments(extract_dir, archive_dir)
    combined = module.combine_evidence_indexes(archive_dir)
    note_budget = module.write_note_budget(archive_dir, subtitle_info, comment_info, combined)
    article_info = {"available": False, "reason": "not an opus"}
    module.write_readme(archive_dir, subtitle_info, article_info, comment_info, metadata_info, note_budget)

    assert metadata_info
    assert subtitle_info["subtitle_lines"] == 2
    assert subtitle_info["evidence_blocks"] == 1
    assert comment_info["jsonl_records"] == 2
    assert comment_info["evidence_blocks"] == 2
    assert combined == 3
    assert note_budget["recommended_note_chars_min"] >= 1200
    assert note_budget["recommended_note_chars_max"] >= note_budget["recommended_note_chars_min"]
    assert note_budget["granularity"] == "short_video"
    assert (archive_dir / "metadata" / "note_budget.json").exists()
    readme = (archive_dir / "README.md").read_text(encoding="utf-8")
    assert "## 先看哪里" in readme
    assert "## 推荐用法" in readme
    assert "笔记预算" in readme
    assert "{'available':" not in readme
    evidence = (archive_dir / "indexes" / "证据索引.jsonl").read_text(encoding="utf-8")
    assert "P01@00:00:00-00:00:02" in evidence
    assert "C1" in evidence
    assert "C2" in evidence


def test_archive_articles_builds_indexes_and_article_budget(tmp_path):
    module = load_module()
    extract_dir = tmp_path / "extract"
    archive_dir = tmp_path / "archive"
    extract_dir.mkdir()

    (extract_dir / "article_content.md").write_text("# 图文标题\n\n正文内容\n", encoding="utf-8")
    (extract_dir / "article_content.txt").write_text("正文内容\n", encoding="utf-8")
    (extract_dir / "article_content.jsonl").write_text(
        json.dumps({"block_id": "O123-B001", "text": "正文内容"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (extract_dir / "article_evidence.jsonl").write_text(
        json.dumps({"evidence_id": "O123-E001", "text": "正文内容"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_json(extract_dir / "images_manifest.json", {"opus_id": "123", "images": [{"index": 1, "url": "https://i0.hdslb.com/a.jpg"}]})
    write_json(
        extract_dir / "opus_normalized.json",
        {
            "source": "https://www.bilibili.com/opus/123",
            "id_str": "123",
            "title": "图文标题",
            "author": {"name": "UP", "pub_time": "2026-01-01 00:00:00"},
        },
    )
    write_json(
        extract_dir / "metadata.json",
        {
            "data": {
                "pubdate": 1767225600,
                "stat": {"view": 0, "reply": 2, "favorite": 3, "coin": 0, "share": 1, "like": 8, "danmaku": 0},
            }
        },
    )

    metadata_info = module.archive_metadata(extract_dir, archive_dir)
    subtitle_info = module.archive_subtitles(extract_dir, archive_dir)
    article_info = module.archive_articles(extract_dir, archive_dir)
    comment_info = module.archive_comments(extract_dir, archive_dir)
    combined = module.combine_evidence_indexes(archive_dir)
    note_budget = module.write_note_budget(archive_dir, subtitle_info, comment_info, combined, article_info)
    module.write_readme(archive_dir, subtitle_info, article_info, comment_info, metadata_info, note_budget)

    assert article_info["available"] is True
    assert article_info["article_chars"] == 4
    assert article_info["blocks"] == 1
    assert article_info["evidence_blocks"] == 1
    assert article_info["image_count"] == 1
    assert combined == 1
    assert note_budget["content_type"] == "opus"
    assert note_budget["content_chars"] == 4
    assert (archive_dir / "articles" / "图文全文.md").exists()
    assert (archive_dir / "indexes" / "图文证据索引.md").exists()
    readme = (archive_dir / "README.md").read_text(encoding="utf-8")
    assert "图文：" in readme
    assert "O图文证据ID" in readme


def test_sparse_video_subtitles_warn_visual_dependency(tmp_path):
    module = load_module()
    archive_dir = tmp_path / "archive"
    subtitle_info = {
        "available": True,
        "parts": 1,
        "duration_minutes": 45,
        "subtitle_lines": 3,
        "subtitle_chars": 120,
        "subtitle_chars_per_minute": 2.667,
        "evidence_blocks": 1,
    }
    comment_info = {"available": False}

    note_budget = module.write_note_budget(archive_dir, subtitle_info, comment_info, evidence_count=1)
    module.write_readme(archive_dir, subtitle_info, {"available": False}, comment_info, {}, note_budget)

    assert note_budget["visual_dependency"]["risk"] == "high"
    assert note_budget["visual_dependency"]["needs_visual_review"] is True
    assert note_budget["visual_dependency"]["requires_multimodal_model"] is True
    assert note_budget["evidence_warnings"]
    assert "多模态视觉理解" in note_budget["writing_guidance"]
    readme = (archive_dir / "README.md").read_text(encoding="utf-8")
    assert "画面依赖提示" in readme


def test_archive_subtitles_falls_back_to_existing_clean_manifest(tmp_path):
    module = load_module()
    extract_dir = tmp_path / "extract"
    archive_dir = tmp_path / "archive"
    subtitle_txt = archive_dir / "subtitles" / "txt" / "p01.txt"
    subtitle_txt.parent.mkdir(parents=True)
    subtitle_txt.write_text("第一行\n第二行\n", encoding="utf-8")
    write_json(
        archive_dir / "metadata" / "subtitles_manifest.clean.json",
        {
            "parts": 66,
            "outputs": [{"duration": 3600, "line_count": 2, "txt": str(subtitle_txt)}],
            "subtitle_lines": 1000,
            "evidence_blocks": 120,
        },
    )

    subtitle_info = module.archive_subtitles(extract_dir, archive_dir)

    assert subtitle_info["available"] is True
    assert subtitle_info["from_existing_archive"] is True
    assert subtitle_info["parts"] == 66
    assert subtitle_info["duration_minutes"] == 60
    assert subtitle_info["subtitle_chars"] == 6


def test_archive_subtitles_uses_asr_transcripts_from_run_summary(tmp_path):
    module = load_module()
    extract_dir = tmp_path / "extract"
    archive_dir = tmp_path / "archive"
    transcript_json = extract_dir / "p01.json"
    transcript_txt = extract_dir / "p01.txt"
    transcript_txt.parent.mkdir(parents=True)
    transcript_txt.write_text("第一句 RAG 第二句 embedding\n", encoding="utf-8")
    write_json(
        transcript_json,
        {
            "segments": [
                {"start": 0.0, "end": 1.5, "text": "第一句 RAG"},
                {"start": 1.5, "end": 3.0, "text": "第二句 embedding"},
            ]
        },
    )
    write_json(
        extract_dir / "browser_ai_subtitle_manifest.json",
        {
            "bvid": "BVasr",
            "aid": 456,
            "outputs": [
                {
                    "page": 1,
                    "cid": "789",
                    "part": "ASR 测试",
                    "duration": 3,
                    "subtitle": None,
                    "error": "no subtitle_url",
                }
            ],
        },
    )
    write_json(
        extract_dir / "run_summary.json",
        {
            "bvid": "BVasr",
            "aid": 456,
            "transcripts": [
                {
                    "page": 1,
                    "cid": "789",
                    "part": "ASR 测试",
                    "duration": 3,
                    "transcript_txt": str(transcript_txt),
                    "transcript_json": str(transcript_json),
                }
            ],
        },
    )

    subtitle_info = module.archive_subtitles(extract_dir, archive_dir)

    assert subtitle_info["available"] is True
    assert subtitle_info["parts"] == 1
    assert subtitle_info["subtitle_lines"] == 2
    assert subtitle_info["evidence_blocks"] == 1
    evidence = (archive_dir / "indexes" / "字幕证据索引.jsonl").read_text(encoding="utf-8")
    assert "P01@00:00:00-00:00:03" in evidence
    assert "embedding" in evidence


def test_quality_metrics_use_engagement_and_publish_age(tmp_path):
    module = load_module()
    archive_dir = tmp_path / "archive"
    write_json(
        archive_dir / "metadata" / "metadata.json",
        {
            "data": {
                "pubdate": 1735689600,
                "stat": {
                    "view": 100000,
                    "danmaku": 500,
                    "reply": 800,
                    "favorite": 6000,
                    "coin": 3000,
                    "share": 900,
                    "like": 8000,
                },
            }
        },
    )

    metrics = module.extract_quality_metrics(
        archive_dir,
        now=datetime(2025, 4, 11, tzinfo=timezone.utc),
    )

    assert metrics["available"] is True
    assert metrics["days_since_publish"] == 100
    assert metrics["quality_multiplier"] > 1.0
    assert metrics["favorite_rate"] == 0.06
