import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "extract_bilibili_opus.py"


def load_module():
    spec = importlib.util.spec_from_file_location("extract_bilibili_opus", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def word(text):
    return {"word": {"words": text}}


def sample_state():
    return {
        "detail": {
            "id_str": "1194341967364882439",
            "type": 1,
            "basic": {
                "comment_type": 12,
                "comment_id_str": "48091857",
                "rid_str": "48091857",
                "title": "RAG 是什么",
                "uid": "12890453",
                "article_type": 4,
            },
            "modules": [
                {"module_type": "MODULE_TYPE_TITLE", "module_title": {"text": "RAG 是什么"}},
                {"module_type": "MODULE_TYPE_AUTHOR", "module_author": {"name": "测试UP", "mid": "12890453", "pub_ts": 1782000000}},
                {
                    "module_type": "MODULE_TYPE_CONTENT",
                    "module_content": {
                        "paragraphs": [
                            {"para_type": 8, "heading": {"level": 2, "nodes": [word("核心定义")]}},
                            {"para_type": 1, "text": {"nodes": [word("RAG 是检索增强生成。")]}},
                            {
                                "para_type": 2,
                                "pic": {
                                    "pics": [
                                        {
                                            "url": "//i0.hdslb.com/bfs/article/test.jpg",
                                            "width": 640,
                                            "height": 360,
                                            "size": 123,
                                            "comment": "流程图",
                                        }
                                    ]
                                },
                            },
                            {"para_type": 7, "code": {"lang": "python", "content": "print('rag')"}},
                            {
                                "para_type": 5,
                                "list": {
                                    "style": 0,
                                    "children": [
                                        {"level": 1, "children": [{"para_type": 1, "text": {"nodes": [word("先切分文档")]}}]},
                                    ],
                                },
                            },
                        ]
                    },
                },
                {
                    "module_type": "MODULE_TYPE_STAT",
                    "module_stat": {
                        "like": {"count": 8},
                        "comment": {"count": 6},
                        "favorite": {"count": 3},
                        "coin": {"count": 1},
                        "forward": {"count": 2},
                    },
                },
            ],
        }
    }


def test_extract_opus_id_supports_opus_dynamic_and_plain_id():
    module = load_module()

    assert module.extract_opus_id("https://www.bilibili.com/opus/1194341967364882439?from=search") == "1194341967364882439"
    assert module.extract_opus_id("https://t.bilibili.com/dynamic/1194341967364882439") == "1194341967364882439"
    assert module.extract_opus_id("1194341967364882439") == "1194341967364882439"


def test_build_outputs_renders_article_blocks_images_and_evidence():
    module = load_module()

    outputs = module.build_outputs(sample_state(), "https://www.bilibili.com/opus/1194341967364882439")

    assert outputs["normalized"]["title"] == "RAG 是什么"
    assert outputs["normalized"]["comment"] == {"type": 12, "oid": "48091857"}
    assert outputs["normalized"]["image_count"] == 1
    assert outputs["normalized"]["block_count"] == 5
    assert "## 核心定义" in outputs["markdown"]
    assert "![流程图](https://i0.hdslb.com/bfs/article/test.jpg)" in outputs["markdown"]
    assert "```python" in outputs["markdown"]
    assert "- 先切分文档" in outputs["markdown"]
    assert outputs["evidence"][0]["evidence_id"] == "O1194341967364882439-E001"


def test_write_outputs_without_image_download_creates_queryable_files(tmp_path):
    module = load_module()
    outputs = module.build_outputs(sample_state(), "https://www.bilibili.com/opus/1194341967364882439")

    summary = module.write_outputs(tmp_path, sample_state(), outputs, download=False, force=False)

    assert summary["kind"] == "opus"
    assert summary["image_count"] == 1
    assert summary["downloaded_images"] == 0
    assert (tmp_path / "article_content.md").exists()
    assert (tmp_path / "article_content.jsonl").exists()
    assert (tmp_path / "article_evidence.jsonl").exists()
    manifest = json.loads((tmp_path / "images_manifest.json").read_text(encoding="utf-8"))
    assert manifest["images"][0]["url"] == "https://i0.hdslb.com/bfs/article/test.jpg"


def test_fetch_opus_comments_uses_comment_type_and_oid(monkeypatch, tmp_path):
    module = load_module()
    outputs = module.build_outputs(sample_state(), "https://www.bilibili.com/opus/1194341967364882439")
    calls = {}

    class FakeExtractor:
        def fetch_comments(self, oid, bvid, out_dir, mode=3, target_type=1, source=None):
            calls.update({"oid": oid, "bvid": bvid, "out_dir": out_dir, "target_type": target_type, "source": source})
            return {"target_type": target_type, "oid": oid, "top_level_count": 1}

    monkeypatch.setattr(module, "load_video_extractor", lambda: FakeExtractor())

    result = module.fetch_opus_comments(outputs, tmp_path)

    assert result["top_level_count"] == 1
    assert calls["oid"] == "48091857"
    assert calls["bvid"] is None
    assert calls["target_type"] == 12
    assert calls["source"] == "https://www.bilibili.com/opus/1194341967364882439"
