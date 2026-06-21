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

## 输出内容

一次完整提取会生成两层结果：面向阅读的主笔记，以及面向复核和追问的原始材料包。主笔记强调学习收获、关键概念、方法流程、实践清单和证据位置；材料包保存完整字幕、评论、元数据、JSONL 索引、预算和评分结果。

<details>
<summary>展开完整输出清单</summary>

主笔记通常包含：

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

原始材料包通常包含：

- 完整字幕文本、SRT 和原始 JSON
- 完整评论与评论 JSONL
- 字幕全集和评论全集
- 字幕证据索引、评论证据索引、合并证据索引
- 视频元数据、字幕清单、评论清单
- 笔记预算和评分结果

</details>

## 快速使用

### 1. 安装

把下面这句话发给 Agent：

```text
请帮我安装这个 skill：
https://github.com/Rimagination/bili-note
```

### 2. 提取视频

在 B 站视频页点击分享，复制视频链接，然后把下面这句话发给 Agent：

```text
请帮我提取这个视频的内容：https://www.bilibili.com/video/BVxxxx/
```

如果也想提取评论区里的有用内容，可以说：

```text
请帮我提取这个视频的内容和评论区有用的内容：https://www.bilibili.com/video/BVxxxx/
```

### 3. 指定保存位置

如果你有固定文件夹，或者想保存到 Obsidian 知识库里，再加一句保存路径：

```text
帮我存放在：“D:\知识库\B站总结” 里
```

## 依赖说明

Bili Note 的默认路线尽量少依赖：元数据、公开字幕、评论、归档、证据索引和笔记预算都使用 Python 标准库，不需要先安装一堆 Python 包。网页 AI 字幕和音频转写属于增强路线，只有默认字幕不可用或用户明确需要兜底时才用。

第一次使用或换机器后，可以先把这句话发给 Agent：

```text
请帮我检查 Bili Note 的运行环境是否就绪，并告诉我当前适合走字幕、网页 AI 字幕还是音频转写路线。
```

Agent 会运行：

```powershell
python scripts/check_environment.py
```

这个检查会覆盖 Python、本 skill 的脚本完整性、B 站公开接口、`web-access` 浏览器入口、`ffmpeg`、ASR 后端、`yt-dlp` 和 `pytest`。

依赖按能力分层理解：

| 层级 | 用来做什么 | 需要什么 | 缺失时怎么办 |
| --- | --- | --- | --- |
| 必需 | 启动核心工作流 | Python 3.10+、已安装本 skill、能访问 B 站公开接口 | 先修复 Python 或重新安装 skill |
| 默认路线 | 抓元数据、公开字幕、评论、归档、生成索引和预算 | 无第三方 Python 包，使用标准库 | 这条路线应优先尝试 |
| 推荐增强 | 获取网页播放器里的 B 站 AI 字幕 | `web-access` skill、已打开并登录的 B 站视频页、浏览器 target id | 没有时跳过网页 AI 字幕，说明覆盖范围 |
| 可选兜底 | 视频完全没有可用字幕时做音频转写 | `ffmpeg`，以及 `faster-whisper` / `funasr` / `openai-whisper` 任一 ASR 后端；`yt-dlp` 只在音频下载失败时需要 | 不默认安装；只有用户要求无字幕也要转写时再补 |
| 开发测试 | 跑本项目测试 | `pytest` | 普通使用不需要 |

因此，只装这个 skill 也可以先完成大多数公开视频的字幕、评论和归档；缺少的依赖只会影响相应的增强能力，不代表整个 skill 不可用。

## 写笔记的原则

- 先讲“为什么”和“怎么迁移使用”，再讲“视频说了什么”。
- 课程型视频按学习模块组织，不按分 P 机械流水账压缩。
- 观点型视频按问题背景、作者判断、论据、适用边界和启发来整理。
- 技术教程保留架构、数据流、代码思路、配置项、评估方式和排错路径。
- 评论区只保留纠错、补充案例、实践经验、替代方案和争议点。
- 关键判断尽量标注 `Pxx@hh:mm:ss-hh:mm:ss` 或评论证据 `C<rpid>`，方便回查完整原文。

## 相关文件

- `SKILL.md`：Codex 使用这个 skill 时读取的完整工作流说明。
- `scripts/check_environment.py`：检查核心工作流、B 站公开接口、网页 AI 字幕、音频 ASR 和测试依赖是否可用。
- `scripts/run_bili_note.py`：一键运行元数据、字幕、评论、归档和证据索引流程。
- `scripts/extract_bilibili.py`：抓取元数据、字幕、音频、ASR 和评论。
- `scripts/fetch_browser_ai_subtitles.py`：通过已登录网页播放器下载 B 站 AI 字幕。
- `scripts/archive_bili_materials.py`：归档完整材料并生成全文索引和证据索引。
- `scripts/score_bili_note.py`：按预算校验主笔记长度、压缩比和证据引用。
- `scripts/update_note_budget_section.py`：把预算、互动质量和信噪比评分写回主笔记。

## 致谢

Bili Note 的设计和实现参考、依托了这些主要项目与生态：

- [Bilibili](https://www.bilibili.com/)：视频、字幕、评论和互动数据来源。
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)：可选音频下载兜底。
- [FFmpeg](https://ffmpeg.org/)：可选音频转码。
- [OpenAI Whisper](https://github.com/openai/whisper)、[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[FunASR](https://github.com/modelscope/FunASR)：可选 ASR 转写后端。
- [pytest](https://pytest.org/) 与 [Shields.io](https://shields.io/)：测试框架和 README 徽章服务。

## 许可证

本项目使用 MIT License，详见 `LICENSE`。
