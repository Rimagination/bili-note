<p align="center">
  <img src="assets/bili-note-logo.png" alt="Bili Note logo" width="560">
</p>

<p align="center">
  <img alt="Bilibili" src="https://img.shields.io/badge/Bilibili-video_notes-00A1D6?style=for-the-badge">
  <img alt="Markdown" src="https://img.shields.io/badge/Markdown-knowledge_base-222222?style=for-the-badge&logo=markdown">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-FF6699?style=for-the-badge">
</p>

# Bili Note

Bili Note 是一个面向知识库的 B 站视频笔记工具：完整归档字幕与评论，按内容信息量和视频质量动态控制笔记长度，把视频整理成可学习、可检索、可追问的 Markdown 笔记。

它的核心特点是：

- 完整归档：保存完整字幕、完整评论、元数据和证据索引，主笔记中的关键判断可以回到原文位置复核。
- 非固定长度：不把短视频和长课程压成同样字数，而是按信息量和内容结构决定提炼粒度。
- 质量感知：结合视频热度、互动质量、评论讨论度和发布时间等信号调整笔记预算，让更值得深读的视频获得更充分的整理。

它的目标不是把视频压成几句摘要，而是生成一份“学完这节课之后真的有收获”的学习型笔记。

## 适合什么

- 提炼 B 站技术视频、课程、观点视频和多 P 系列课。
- 把完整字幕、评论、元数据和证据索引长期保存到知识库。
- 为人类阅读和 Agent 后续问答准备可引用的证据。
- 根据视频时长、字幕字数、互动热度和评论量控制笔记详略，避免长课和短视频都被压成同样长度。

## 输出什么

一次完整提取通常会生成两类内容。

主笔记是给人读的 Markdown，默认包含：

- 学完你应该获得什么
- 一句话总论
- 适用场景与前置知识
- 知识地图
- 核心概念卡
- 方法或流程
- 关键洞察
- 实践清单
- 坑点与反例
- 自测题
- 笔记预算与信噪比
- 证据与原文位置
- 来源、覆盖与局限

原始材料包是给追问和复核用的长期归档，通常包含：

- 完整字幕文本、SRT 和原始 JSON
- 完整评论与评论 JSONL
- 字幕全集和评论全集
- 字幕证据索引、评论证据索引、合并证据索引
- 视频元数据、字幕清单、评论清单
- 笔记预算和评分结果

## 快速使用

在 PowerShell 中设置 skill 路径：

```powershell
$skill = "$env:USERPROFILE\.codex\skills\bili-note"
$py = "python"
```

提取一个视频并归档字幕、评论和证据索引：

```powershell
& $py "$skill\scripts\run_bili_note.py" "https://www.bilibili.com/video/BVxxxx/" `
  --work-dir ".\tmp_bili_extract" `
  --archive-dir "D:\knowledge\知识库\Rag技术\原始材料\BVxxxx_视频短标题" `
  --comments
```

写完主笔记后，刷新预算与信噪比小节：

```powershell
& $py "$skill\scripts\update_note_budget_section.py" `
  --archive-dir "D:\knowledge\知识库\Rag技术\原始材料\BVxxxx_视频短标题" `
  --note-path "D:\knowledge\知识库\Rag技术\观点X：视频短标题.md"
```

## 写笔记的原则

- 先讲“为什么”和“怎么迁移使用”，再讲“视频说了什么”。
- 课程型视频按学习模块组织，不按分 P 机械流水账压缩。
- 观点型视频按问题背景、作者判断、论据、适用边界和启发来整理。
- 技术教程保留架构、数据流、代码思路、配置项、评估方式和排错路径。
- 评论区只保留纠错、补充案例、实践经验、替代方案和争议点。
- 关键判断尽量标注 `Pxx@hh:mm:ss-hh:mm:ss` 或评论证据 `C<rpid>`，方便回查完整原文。

## 相关文件

- `SKILL.md`：Codex 使用这个 skill 时读取的完整工作流说明。
- `scripts/run_bili_note.py`：一键运行元数据、字幕、评论、归档和证据索引流程。
- `scripts/extract_bilibili.py`：抓取元数据、字幕、音频、ASR 和评论。
- `scripts/fetch_browser_ai_subtitles.py`：通过已登录网页播放器下载 B 站 AI 字幕。
- `scripts/archive_bili_materials.py`：归档完整材料并生成全文索引和证据索引。
- `scripts/score_bili_note.py`：按预算校验主笔记长度、压缩比和证据引用。
- `scripts/update_note_budget_section.py`：把预算、互动质量和信噪比评分写回主笔记。

## 许可证

本项目使用 MIT License，详见 `LICENSE`。
