import json
import subprocess
import sys
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_bili_note.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_bili_note", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_run_bili_note_help_exposes_pipeline_options():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "--archive-dir" in result.stdout
    assert "--browser-target" in result.stdout
    assert "--subtitle-mode" in result.stdout
    assert "--download-images" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--visual-review" in result.stdout
    assert "--browser" in result.stdout
    assert "--edge-cdp-url" in result.stdout


def test_run_bili_note_detects_video_and_opus_sources():
    module = load_module()

    assert module.source_kind("https://www.bilibili.com/video/BV1abc/") == "video"
    assert module.find_source_id("https://www.bilibili.com/video/BV1abc/") == "BV1abc"
    assert module.source_kind("https://www.bilibili.com/opus/1194341967364882439?from=search") == "opus"
    assert module.find_source_id("https://www.bilibili.com/opus/1194341967364882439?from=search") == "1194341967364882439"
    assert module.source_kind("1194341967364882439") == "opus"


def test_visual_review_requires_an_explicit_choice_when_asked():
    module = load_module()

    assert module.resolve_visual_review("on") == "on"
    assert module.resolve_visual_review("off") == "off"


def test_edge_browser_route_receives_parts_and_cdp_options(tmp_path, monkeypatch):
    module = load_module()
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "metadata.json").write_text('{"data": {"duration": 60, "videos": 1, "pages": []}}', encoding="utf-8")
    seen = []

    def fake_run_cmd(cmd, dry_run=False):
        seen.append(cmd)
        return {"cmd": cmd, "returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(module, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "BV1abc",
            "--work-dir",
            str(work_dir),
            "--browser",
            "edge",
            "--edge-cdp-url",
            "http://127.0.0.1:9333",
            "--subtitle-mode",
            "browser",
            "--parts",
            "2,20",
            "--visual-review",
            "off",
            "--no-archive",
        ],
    )

    assert module.main() == 0
    browser_cmd = next(cmd for cmd in seen if str(module.BROWSER_AI_SCRIPT) in cmd)
    assert browser_cmd[browser_cmd.index("--parts") + 1] == "2,20"
    assert "--browser" in browser_cmd
    assert browser_cmd[browser_cmd.index("--edge-cdp-url") + 1] == "http://127.0.0.1:9333"


def test_visual_preflight_recommends_keyframes_for_sparse_long_video(tmp_path):
    module = load_module()
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "metadata.json").write_text(
        json.dumps(
            {
                "data": {
                    "duration": 3600,
                    "videos": 1,
                    "pages": [{"page": 1, "cid": 123, "duration": 3600}],
                }
            }
        ),
        encoding="utf-8",
    )
    subtitle = work_dir / "p01.txt"
    subtitle.write_text("字幕很少\n" * 20, encoding="utf-8")
    (work_dir / "subtitle_manifest.json").write_text(
        json.dumps([{"page": 1, "txt": str(subtitle)}]),
        encoding="utf-8",
    )

    preflight = module.visual_preflight(work_dir, "all")

    assert preflight["status"] == "ok"
    assert preflight["risk"] == "high"
    assert preflight["subtitle_chars"] == 80
    assert "建议开启" in preflight["recommendation"]


def test_visual_preflight_allows_disabling_for_dense_short_video(tmp_path):
    module = load_module()
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "metadata.json").write_text(
        json.dumps(
            {
                "data": {
                    "duration": 600,
                    "videos": 1,
                    "pages": [{"page": 1, "cid": 123, "duration": 600}],
                }
            }
        ),
        encoding="utf-8",
    )
    subtitle = work_dir / "p01.txt"
    subtitle.write_text("完整字幕内容。" * 200, encoding="utf-8")
    (work_dir / "subtitle_manifest.json").write_text(
        json.dumps([{"page": 1, "txt": str(subtitle)}]),
        encoding="utf-8",
    )

    preflight = module.visual_preflight(work_dir, "all")

    assert preflight["risk"] == "low"
    assert "可以关闭" in preflight["recommendation"]


def test_keyframe_manifest_is_required_for_cached_visual_review(tmp_path):
    module = load_module()
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    assert not module.keyframes_available(work_dir)

    (work_dir / "keyframes").mkdir()
    (work_dir / "keyframes" / "contact_sheet.png").write_bytes(b"png")
    (work_dir / "keyframes" / "frames").mkdir()
    (work_dir / "keyframes" / "frames" / "frame_001.png").write_bytes(b"png")
    (work_dir / "keyframes_manifest.json").write_text(
        '{"status": "ok", "bvid": "BV1abc", "parts": "all", "frame_count": 1, "requested_video_source": "auto", "frames": [{"evidence_id": "KF-P01-01", "file": "keyframes/frames/frame_001.png"}]}',
        encoding="utf-8",
    )

    assert module.keyframes_available(work_dir)
    assert module.keyframes_available(work_dir, source="BV1abc", parts="all", count=1, video_source="auto")


def test_archive_cache_is_rebuilt_when_keyframes_are_new(tmp_path):
    module = load_module()
    archive_dir = tmp_path / "archive"
    work_dir = tmp_path / "work"
    (archive_dir / "indexes").mkdir(parents=True)
    (archive_dir / "metadata").mkdir(parents=True)
    (archive_dir / "keyframes" / "frames").mkdir(parents=True)
    (work_dir / "keyframes" / "frames").mkdir(parents=True)
    (archive_dir / "indexes" / "证据索引.jsonl").write_text("{}\n", encoding="utf-8")
    for root in (archive_dir, work_dir):
        (root / "keyframes" / "contact_sheet.png").write_bytes(b"sheet")
        (root / "keyframes" / "frames" / "frame_001.png").write_bytes(b"frame")

    manifest = {
        "status": "ok",
        "bvid": "BV1abc",
        "parts": "all",
        "frame_count": 1,
        "sheet": "keyframes/contact_sheet.png",
        "frames": [{"evidence_id": "KF-P01-01", "file": "keyframes/frames/frame_001.png"}],
    }
    (archive_dir / "metadata" / "keyframes_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (work_dir / "keyframes_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert module.archive_available(
        archive_dir,
        require_keyframes=True,
        keyframe_manifest_path=work_dir / "keyframes_manifest.json",
    )
    assert not module.archive_available(archive_dir, visual_review="off")

    changed = {**manifest, "frame_count": 2}
    (work_dir / "keyframes_manifest.json").write_text(json.dumps(changed), encoding="utf-8")
    assert not module.archive_available(
        archive_dir,
        require_keyframes=True,
        keyframe_manifest_path=work_dir / "keyframes_manifest.json",
    )
