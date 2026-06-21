from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_skill_requires_learning_oriented_notes():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "学习型笔记" in text
    assert "学完你应该获得什么" in text
    assert "核心概念卡" in text
    assert "实践清单" in text
    assert "自测题" in text
    assert "不合格信号" in text
