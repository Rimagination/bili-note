import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "extract_video_keyframes.py"


def load_module():
    spec = importlib.util.spec_from_file_location("extract_video_keyframes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_frame_points_cover_selected_parts_by_duration():
    module = load_module()
    pages = [
        {"page": 1, "cid": 101, "part": "第一部分", "duration": 10},
        {"page": 2, "cid": 202, "part": "第二部分", "duration": 30},
    ]

    points = module.frame_points(pages, 12)

    assert len(points) == 12
    assert points[0]["page"] == 1
    assert points[-1]["page"] == 2
    assert sum(point["page"] == 2 for point in points) > sum(point["page"] == 1 for point in points)
    assert all(point["timestamp"] for point in points)


def test_frame_points_cover_each_part_when_budget_allows():
    module = load_module()
    pages = [
        {"page": 1, "cid": 101, "duration": 1},
        {"page": 2, "cid": 202, "duration": 1},
        {"page": 3, "cid": 303, "duration": 1},
    ]

    points = module.frame_points(pages, 3)

    assert {point["page"] for point in points} == {1, 2, 3}


def test_keyframe_readme_links_are_relative_to_keyframe_directory(tmp_path):
    module = load_module()
    keyframe_dir = tmp_path / "keyframes"
    keyframe_dir.mkdir()
    manifest = {
        "sheet": "keyframes/contact_sheet.png",
        "frames": [
            {
                "evidence_id": "KF-P01-01",
                "page": 1,
                "timestamp": "00:00:05",
                "file": "keyframes/frames/frame_001.png",
            }
        ],
    }

    module.write_keyframe_readme(keyframe_dir, manifest)
    readme = (keyframe_dir / "README.md").read_text(encoding="utf-8")

    assert "[frame_001.png](frames/frame_001.png)" in readme
