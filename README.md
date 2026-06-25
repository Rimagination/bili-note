<p align="center">
  <img src="assets/bili-note-logo.png" alt="Bili Note logo" width="560">
</p>

<p align="center">
  <img alt="Bilibili" src="https://img.shields.io/badge/Bilibili-video_%2B_opus-00A1D6?style=for-the-badge">
  <img alt="Markdown" src="https://img.shields.io/badge/Markdown-knowledge_base-222222?style=for-the-badge&logo=markdown">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-FF6699?style=for-the-badge">
</p>

# Bili Note

Bili Note 是一个面向知识库的 B 站视频与图文笔记工具：完整归档字幕、图文正文、图片与评论，按内容信息量和质量动态控制笔记长度，把 B 站内容整理成可学习、可检索、可追问的 Markdown 笔记。

它的核心特点是：

- 完整归档：保存完整字幕、图文正文、图片、完整评论、元数据和证据索引，主笔记中的关键判断可以通过论文式编号链接回到原文位置复核。
- 非固定长度：不把短视频和长课程压成同样字数，而是按信息量和内容结构决定提炼粒度。
- 质量感知：结合内容热度、互动质量、评论讨论度和发布时间等信号调整笔记预算，让更值得深读的内容获得更充分的整理。
- 写前定标：先根据原始材料生成推荐字数、压缩比和写作粒度，再开始写笔记；写后评分只用于验收和微调。

它的目标不是把内容压成几句摘要，而是生成一份“学完这节课或读完这篇教程之后真的有收获”的学习型笔记。

## 适合什么

- 提炼 B 站技术视频、课程、观点视频、多 P 系列课和图文/动态/opus 长文。
- 把完整字幕、图文正文、图片、评论、元数据和证据索引长期保存到知识库。
- 为人类阅读和 Agent 后续问答准备可引用的证据。
- 根据视频时长、字幕字数、图文正文量、互动热度和评论量控制笔记详略，避免长课、短视频和长图文都被压成同样长度。
- 先用预算确定目标字数和结构密度，再写主笔记，减少写完后大幅返工。

## 输出内容

一次完整提取会生成两层结果：面向阅读的主笔记，以及面向复核和追问的原始材料包。主笔记会先依据材料包里的预算确定详略，再组织学习收获、关键概念、方法流程、实践清单和证据位置；材料包保存完整字幕或图文正文、图片、评论、元数据、JSONL 索引、写前预算和写后评分结果。

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
- 证据脚注与原文位置
- 来源、覆盖与局限

原始材料包通常包含：

- 完整图文 Markdown、纯文本、图片清单和本地图片
- 图文全文索引和图文证据索引
- 完整字幕文本、SRT 和原始 JSON
- 完整评论与评论 JSONL
- 字幕全集和评论全集
- 字幕证据索引、图文证据索引、评论证据索引、合并证据索引
- 内容元数据、字幕清单、图文清单、评论清单
- 笔记预算和评分结果

</details>

## 快速使用

### 1. 安装

把下面这句话发给 Agent：

```text
请帮我安装这个 skill：
https://github.com/Rimagination/bili-note
```

### 2. 提取视频或图文

在 B 站视频页点击分享，复制视频链接，然后把下面这句话发给 Agent：

```text
请帮我提取这个视频的内容：https://www.bilibili.com/video/BVxxxx/
```

如果也想提取评论区里的有用内容，可以说：

```text
请帮我提取这个视频的内容和评论区有用的内容：https://www.bilibili.com/video/BVxxxx/
```

图文/动态/opus 链接也一样：

```text
请帮我提取这个 B 站图文的内容：https://www.bilibili.com/opus/1194341967364882439
```

需要评论区时可以说：

```text
请帮我提取这个 B 站图文的内容和评论区有用的内容：https://www.bilibili.com/opus/1194341967364882439
```

### 3. 指定保存位置

如果你有固定文件夹，或者想保存到 Obsidian 知识库里，再加一句保存路径：

```text
帮我存放在：“D:\知识库\B站总结” 里
```

## 依赖与环境检测

第一次使用、换机器、字幕路线失败，或准备转写音频前，先让 Agent 检查环境：

```text
请帮我检查 Bili Note 的运行环境，并告诉我当前能走公开字幕、网页 AI 字幕、中文 Qwen3-ASR 还是 Whisper 兜底。
```

Agent 会运行：

```powershell
python scripts/check_environment.py
```

Bili Note 和 DyNote 会共享可复用资源。默认共享目录是：

```text
%USERPROFILE%\.cache\rimagination-notes
```

其中 Qwen3-ASR 虚拟环境默认放在：

```text
%USERPROFILE%\.cache\rimagination-notes\qwen3-asr-venv
```

因此，只要任意一个 skill 已经引导你安装过 Qwen3-ASR，另一个 skill 会优先复用同一套环境和模型缓存。Hugging Face 模型缓存、Whisper 缓存和 faster-whisper 缓存也按本机通用缓存复用，不会绑定到某一个 skill。

依赖按能力分层理解：

| 层级 | 用来做什么 | 需要什么 | 缺失时怎么办 |
| --- | --- | --- | --- |
| 必需 | 启动 skill、抓公开元数据、整理已有材料 | Python 3.10+、已安装本 skill、能访问 B 站公开接口 | 先修复 Python、网络或重新安装 skill |
| 登录浏览器 | 网页 AI 字幕 | Chrome、`web-access`、当前 Chrome 已登录 B 站并打开视频页 | 没有时跳过网页 AI 字幕，说明覆盖范围 |
| 中文转写 | 中文字幕不可用时做高可读转写 | `ffmpeg`、共享 Qwen3-ASR 环境 | 运行 `scripts/setup_qwen_asr_env.py`，两个 skill 共用 |
| 外语转写 | 外语视频转写 | `ffmpeg`、Whisper / faster-whisper | 只有外语视频或 Qwen 不适合时再装 |
| 下载兜底 | B 站公开音频下载失败时兜底 | `yt-dlp` | 需要时再装，不是默认依赖 |
| 开发测试 | 跑本项目测试 | `pytest` | 普通使用不需要 |

默认策略：B 站公开视频优先走公开字幕和网页 AI 字幕；确实需要音频转写时，中文或未指定语言的视频优先 Qwen3-ASR，明确是外语视频时优先 Whisper 系后端。需要手动指定时，可以用 `--asr-backend qwen3-asr` 或 `--asr-backend faster-whisper`。

## 登录和隐私

网页 AI 字幕路线只使用 Chrome + `web-access`：让已登录的 B 站页面自己请求字幕接口。Bili Note 不读取、不导出、不保存 Cookie、localStorage、浏览器 profile 或登录 token。

如果没有可用 Chrome 登录态，Bili Note 会跳过网页 AI 字幕，改用公开字幕、图文正文、评论、音频转写或有限材料整理，并明确说明覆盖范围。Edge、Playwright Chromium 和原生浏览器 CDP 端口目前不能直接替代这条路线。

## 写笔记的原则

- 先讲“为什么”和“怎么迁移使用”，再讲“原内容说了什么”。
- 课程型视频按学习模块组织，不按分 P 机械流水账压缩。
- 观点型视频按问题背景、作者判断、论据、适用边界和启发来整理。
- 技术教程和图文长文保留架构、数据流、代码思路、配置项、图片结论、评估方式和排错路径。
- 评论区只保留纠错、补充案例、实践经验、替代方案和争议点。
- 写笔记前必须先读取 `metadata/note_budget.json`，把推荐字数区间、写作粒度和质量倍率当作写作目标；写完后再用评分做验收。
- 关键判断默认使用论文式编号，例如 `[1][2]`。图文、字幕和评论证据共用同一套编号；文末脚注会链接到完整字幕、图文证据或评论归档，正文不直接堆长证据编号。

## 相关文件

- `SKILL.md`：Codex 使用这个 skill 时读取的完整工作流说明。
- `scripts/check_environment.py`：检查核心工作流、B 站公开接口、网页 AI 字幕、音频转写和测试依赖是否可用。
- `scripts/setup_qwen_asr_env.py`：创建或复用共享 Qwen3-ASR 环境，默认位于 `%USERPROFILE%\.cache\rimagination-notes\qwen3-asr-venv`。
- `scripts/run_qwen_asr.py`：调用 Qwen3-ASR-0.6B，可按 chunk 分段避免显存溢出。
- `scripts/run_bili_note.py`：一键运行视频/图文提取、评论、归档和证据索引流程。
- `scripts/extract_bilibili.py`：抓取元数据、字幕、音频、音频转写和评论。
- `scripts/extract_bilibili_opus.py`：抓取 B 站图文/动态正文、图片、代码块和图文评论。
- `scripts/fetch_browser_ai_subtitles.py`：通过已登录网页播放器下载 B 站 AI 字幕。
- `scripts/archive_bili_materials.py`：归档完整材料并生成全文索引和证据索引。
- `scripts/score_bili_note.py`：按预算验收主笔记长度、压缩比和证据引用。
- `scripts/update_note_budget_section.py`：把预算、互动质量和信噪比评分写回主笔记。

## 社区友链

- [LINUX DO](https://linux.do/)：一个关注开发者、开源项目与 AI 工具交流的社区。感谢社区佬友对开源工具和 Agent 工作流的讨论与反馈。

## 致谢

Bili Note 的设计和实现参考、依托了这些主要项目与生态：

- [Bilibili](https://www.bilibili.com/)：视频、字幕、评论和互动数据来源。
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)：可选音频下载兜底。
- [FFmpeg](https://ffmpeg.org/)：可选音频转码。
- [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-0.6B)：可选中文本地自动语音识别后端。
- [OpenAI Whisper](https://github.com/openai/whisper)、[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[FunASR](https://github.com/modelscope/FunASR)：可选外语视频转写后端。

## 许可证

本项目使用 MIT License，详见 `LICENSE`。
