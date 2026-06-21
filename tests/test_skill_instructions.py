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


def test_skill_declares_chrome_web_access_requirement():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "Chrome + `web-access`" in text
    assert "不要读取或复制 Cookie/profile" in text
    assert "不要强制结束用户浏览器进程" in text
