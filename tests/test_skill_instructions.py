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


def test_skill_declares_browser_ai_subtitle_safety_boundaries():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "Chrome + `web-access`" in text
    assert "不读取、不打印、不复制浏览器 Cookie" in text
    assert "复制用户真实 profile" in text
    assert "强制结束用户正在使用的 Chrome / Edge 进程" in text
    assert "--remote-allow-origins=*" in text
