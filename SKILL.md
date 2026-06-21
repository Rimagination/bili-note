---
name: bili-note
description: Extract Bilibili videos into readable Markdown knowledge notes. Use when the user asks to 提取/提炼/总结/整理 B站 or bilibili video content, save a video note to a local knowledge base, include useful comments, handle multi-part videos, fetch B站 AI subtitles, or fall back to audio transcription.
---

# Bili Note

把 B站视频变成可检索、可复用的 Markdown 知识笔记。优先拿字幕；字幕拿不到时再转写音频；用户要评论区时抓取评论并过滤无关讨论。

联网或登录态操作必须先使用 `web-access`。

网页 AI 字幕当前只支持 Chrome + `web-access` 路线：让已登录的 B站页面自己请求字幕接口。不要把 Edge、Playwright 临时浏览器或原生 CDP 端口当成等价替代，除非脚本已经明确支持。

## 依赖与环境检查

默认路线尽量零第三方 Python 依赖：元数据、公开字幕、评论、归档、证据索引和笔记预算都用标准库完成。网页 AI 字幕和音频 ASR 是增强路线，不是启动门槛。

第一次使用、换机器、用户怀疑依赖不全，或准备使用网页 AI 字幕 / ASR 兜底时，先运行：

```powershell
$skill = "$env:USERPROFILE\.codex\skills\bili-note"
$py = "python"
& $py "$skill\scripts\check_environment.py"
```

根据检查结果选择路线：

- `public_subtitles_comments_archive=OK`：优先走默认字幕、评论和归档流程。
- `browser_ai_subtitles=OK`：当公开接口只有 `ai-zh` 且 `subtitle_url` 为空时，走 Chrome + `web-access` 网页 AI 字幕。
- `audio_asr_fallback=OK`：只有字幕和网页 AI 字幕都不可得、且用户确实需要完整转写时，才走音频 ASR。
- 某个增强能力缺失时，只说明该路线暂不可用；不要把它说成整个 skill 不可用。
- 网页登录态只通过 `web-access` 已授权的 Chrome 页面使用；不要读取或复制 Cookie/profile，不要强制结束用户浏览器进程。没有 Chrome + `web-access` 时就跳过网页 AI 字幕并说明覆盖范围。

## 默认流程

1. 读清用户要什么：视频链接、是否要评论区、保存路径、是否需要全文字幕或只要提炼。
2. 如果是首次使用、依赖状态不明、字幕抓取失败或用户要求 ASR，先用 `check_environment.py` 判断当前可走路线。
3. 优先用 `run_bili_note.py` 一键完成可自动化部分：元数据、字幕、评论、归档、证据索引。
4. 优先下载字幕：
   - 普通字幕 URL 可用时，直接用 `--download-subtitles`。
   - 如果普通接口显示 `ai-zh` 但 `subtitle_url` 为空，不要说“没有字幕”；改走“网页 AI 字幕”流程。
   - 如果字幕仍不可得，再按需要下载音频并用 ASR 转写。
5. 用户要求评论区时，用 `--comments` 抓取主评论和子评论；写入笔记时过滤打卡、求资料、广告、闲聊等技术无关内容。
6. 归档原始材料：把完整字幕、完整评论、元数据和 JSONL 索引存到知识库旁边的长期目录。
7. 读取 `metadata/note_budget.json`：按视频时长、字幕字数、证据块、评论量和互动质量确定笔记字数区间，避免把短视频和长课程压成同一长度。
8. 写 Markdown：默认写成“学习型笔记”，目标是让人或 Agent 像学完一节课一样获得概念、方法、判断标准、实践步骤和自测题；来源、覆盖范围和归档路径放到后半部分。
9. 写完后用 `score_bili_note.py` 校验笔记字数、压缩比、每分钟笔记密度和证据引用比例；太短时优先补“学习收获、知识地图、概念卡、实战流程、坑点、自测题”，不要只堆分P摘要。

## 常用命令

在 PowerShell 中先设定 skill 路径：

```powershell
$skill = "$env:USERPROFILE\.codex\skills\bili-note"
$py = "python"
```

### 0. 检查依赖和可用路线

```powershell
& $py "$skill\scripts\check_environment.py"
```

需要给其他脚本读取时输出 JSON：

```powershell
& $py "$skill\scripts\check_environment.py" --json
```

### 1. 一键提取和归档

默认先用总入口。它会自动跳过已有输出，适合断点续跑。

```powershell
& $py "$skill\scripts\run_bili_note.py" "https://www.bilibili.com/video/BVxxxx/" `
  --work-dir ".\tmp_bili_extract" `
  --archive-dir "D:\knowledge\知识库\Rag技术\原始材料\BVxxxx_视频短标题" `
  --comments
```

如果普通接口没有字幕，但网页播放器能拿到 AI 字幕，先用 `web-access` 打开已登录 Chrome 里的视频页并取得 target id，然后加：

```powershell
--browser-target "CDP_TARGET_ID"
```

运行后先看：

- `bili_note_run_report.md`：本次跑了什么、跳过了什么、下一步读哪里。
- `archive_dir/indexes/证据索引.jsonl`：写总结时可引用的字幕/评论证据块。
- `archive_dir/indexes/字幕全集.md`：完整字幕合集。
- `archive_dir/metadata/note_budget.json`：推荐笔记字数、压缩比和写作粒度。

### 2. 抓元数据和分P目录

```powershell
& $py "$skill\scripts\extract_bilibili.py" "BVxxxx" --out ".\tmp_bili_extract"
```

### 3. 下载普通公开字幕

```powershell
& $py "$skill\scripts\extract_bilibili.py" "BVxxxx" --out ".\tmp_bili_extract" --parts all --download-subtitles
```

### 4. 下载网页 AI 字幕

当 `subtitle_probe.json` 里有 `ai-zh`，但 `subtitle_url` 为空时，使用这条路线。当前脚本需要 Chrome + `web-access` 的 `/targets` 和 `/eval` 代理接口；原生 Edge/Chrome DevTools 端口不能直接传给这个脚本。

1. 用 `web-access` 打开已登录 Chrome 中的 B站视频页，确认页面已加载。
2. 查看浏览器 target id：

```powershell
curl.exe -s http://localhost:3456/targets
```

3. 下载 AI 字幕：

```powershell
& $py "$skill\scripts\fetch_browser_ai_subtitles.py" --target "CDP_TARGET_ID" --out ".\tmp_bili_extract"
```

输出包括：

- `browser_ai_subtitle_urls.json`：每个分P的 AI 字幕 URL。
- `browser_ai_subtitle_manifest.json`：下载清单。
- `browser_ai_subtitles\*.txt`：纯文本字幕。
- `browser_ai_subtitles\*.srt`：SRT 字幕。
- `browser_ai_subtitles\*.subtitle.json`：B站原始字幕 JSON。

这条路线让 B站页面自己用登录态请求 `/x/player/wbi/v2`，不读取、不打印浏览器 cookie。

如果下载到的 AI 字幕明显乱码、内容与标题或课程主题不相干，不要把它当作可靠全文。优先标注“AI 字幕质量不可用”，再考虑 ASR 兜底；若 ASR 也不可用，只能基于分P标题、简介、评论和元数据生成有限学习指南，并明确局限。

### 5. 抓评论区

```powershell
& $py "$skill\scripts\extract_bilibili.py" "BVxxxx" --out ".\tmp_bili_extract" --comments
```

抓取后检查 `comments.md` 和 `comments_raw.json`。写入最终笔记时，只保留与视频主题相关的评论、纠错、技术补充、实践经验和有价值问题。

### 6. 音频 ASR 兜底

只有在字幕和网页 AI 字幕都不可用时才用 ASR。长视频不要默认全量转写，除非用户明确要求。

```powershell
& $py "$skill\scripts\extract_bilibili.py" "BVxxxx" --out ".\tmp_bili_extract" --parts "1,10,38" --download-audio --transcribe --asr-backend auto --asr-model base
```

中文视频优先尝试：

```powershell
& $py "$skill\scripts\extract_bilibili.py" "BVxxxx" --out ".\tmp_bili_extract" --parts "1,10,38" --download-audio --transcribe --asr-backend funasr --asr-model "iic/SenseVoiceSmall"
```

### 7. 归档完整字幕和评论

把临时提取目录整理成长期材料包。这个步骤默认要做，方便后续根据总结继续提问和回查证据。

```powershell
& $py "$skill\scripts\archive_bili_materials.py" --extract-dir ".\tmp_bili_extract" --archive-dir "D:\knowledge\知识库\Rag技术\原始材料\BVxxxx_视频短标题"
```

长期材料包包含：

- `subtitles/txt/`：每个分P的完整纯文本字幕。
- `subtitles/srt/`：每个分P的完整 SRT 字幕和时间轴。
- `subtitles/json/`：B站原始字幕 JSON。
- `comments/comments_raw.json`：完整评论原始结构。
- `comments/评论全集.md`：完整评论 Markdown。
- `indexes/字幕全集.md`：合并后的完整字幕，适合人工阅读。
- `indexes/字幕全集.jsonl`：按字幕片段切分，适合检索和问答。
- `indexes/字幕证据索引.md`：按时间段合并的字幕证据块，适合给总结加引用。
- `indexes/字幕证据索引.jsonl`：按时间段合并的字幕证据块，适合程序检索。
- `indexes/评论全集.jsonl`：按评论/回复切分，适合检索和问答。
- `indexes/评论证据索引.jsonl`：按评论/回复生成的证据块。
- `indexes/证据索引.jsonl`：字幕证据和评论证据的合并索引。
- `metadata/`：视频元数据、字幕清单、评论清单。
- `metadata/note_budget.json`：按视频信息量和互动质量生成的笔记预算，用于控制长短视频的提炼粒度。

### 8. 校验笔记字数和信噪比

写完最终 Markdown 后，用归档目录里的预算给笔记打分：

```powershell
& $py "$skill\scripts\score_bili_note.py" `
  --archive-dir "D:\knowledge\知识库\Rag技术\原始材料\BVxxxx_视频短标题" `
  --note-path "D:\knowledge\知识库\Rag技术\观点X：视频短标题.md" `
  --out "D:\knowledge\知识库\Rag技术\原始材料\BVxxxx_视频短标题\metadata\note_score.json"
```

也可以直接把评分结果写入笔记正文：

```powershell
& $py "$skill\scripts\update_note_budget_section.py" `
  --archive-dir "D:\knowledge\知识库\Rag技术\原始材料\BVxxxx_视频短标题" `
  --note-path "D:\knowledge\知识库\Rag技术\观点X：视频短标题.md"
```

重点看：

- `status`：`too_short` 表示遗漏风险高，`too_long` 表示可能重复堆料，`ok` 表示落在推荐区间。
- `quality_multiplier`：点赞、收藏、投币、评论、弹幕、分享、播放量和发布距今天数形成的互动质量倍率。
- `actual_compression_ratio`：笔记字数 / 字幕字数。长视频应允许更高总字数，但仍要保持压缩。
- `note_chars_per_minute`：每分钟视频对应多少笔记字。长课程不应和短视频接近同一个总字数。
- `evidence_reference_ratio`：笔记中引用的证据块占比。关键判断要能回查 `Pxx@...` 或 `C...`。

## 笔记写法

默认输出必须是“学习型笔记”，不是目录搬运、分P流水账或证据清单。读完后应有“我真的学会了一些东西”的获得感。

### 推荐结构

1. `# 标题`
2. `## 学完你应该获得什么`：用 5-8 条写清楚读者学完后能理解、判断或完成什么。
3. `## 一句话总论`：说明视频最核心的判断，避免只复述标题。
4. `## 适用场景与前置知识`：这套内容适合谁、不适合谁，读者需要先知道什么。
5. `## 知识地图`：把核心概念、模块、流程和它们之间的关系讲清楚。课程型视频要有模块表；短观点视频要有论证链。
6. `## 核心概念卡`：每个重要概念都写成“是什么、为什么重要、怎么用、常见误区、相关证据”。
7. `## 方法或流程`：把视频中的操作、架构、决策流程、参数选择、评估方法抽成可复用步骤。
8. `## 关键洞察`：写作者真正想表达的判断，区分“事实描述、经验判断、推荐做法、限制条件”。
9. `## 实践清单`：给出可以照着做的步骤、检查项、失败信号和排错方向。
10. `## 坑点与反例`：整理视频和评论区提到的踩坑、争议、误区、边界条件。
11. `## 自测题`：写 5-10 个问题和简短答案，帮助人或 Agent 检查是否学会。
12. `## 证据与原文位置`：只放关键证据引用，不要让证据淹没学习内容。
13. `## 来源、覆盖与局限`：URL、BVID、UP、发布时间、字幕/评论覆盖、原始材料路径和局限放在后面。

### 写作标准

- 先解释“为什么”和“怎么迁移使用”，再列“他说了什么”。
- 对课程型长视频，按学习模块组织，不要按分P机械压缩。每个模块至少包含：学习目标、核心概念、关键步骤、常见坑、可操作结论。
- 对观点型短视频，按“问题背景 -> 作者判断 -> 论据 -> 适用边界 -> 对用户的启发”组织。
- 对技术教程，保留架构、数据流、代码思路、配置项、评估方式和排错路径。
- 评论区只写有学习价值的内容：纠错、补充案例、实践经验、替代方案、争议点。
- 证据引用服务于学习，不要把笔记写成引用列表。重要判断尽量标注 `Pxx@hh:mm:ss-hh:mm:ss` 或评论证据 `C<rpid>`。
- 预算偏短时，优先补“概念解释、流程图式文字、实践清单、自测题、反例和边界”，不要只增加摘要段落。
- 热度是“值得多写”的辅助信号，不是替代证据。点赞、收藏、评论、弹幕、投币、分享和发布距今天数会提高或降低推荐字数，但扩写必须来自字幕、评论证据和分P结构。

### 不合格信号

- 开头大段来源信息，读者看半天还不知道学到了什么。
- 只有“核心观点/分P提炼/代表性证据”，没有概念解释、方法步骤和自测。
- 把每个分P压成一句话，长课程读完仍不知道怎么做。
- 只总结作者立场，不写适用条件、反例和失败场景。
- 评论区只是罗列热评，没有转化成纠错、补充或实践提醒。

不要把“只看了标题/目录”的内容写成“完整提取”。如果只抓到部分字幕或只转写了部分分P，明确列出覆盖范围。

## B站字幕注意事项

- 普通 `/x/player/v2` 可能只返回 `ai-zh` 字幕元信息，`subtitle_url` 为空。
- 网页播放器接口 `/x/player/wbi/v2` 常能返回真正的 AI 字幕 URL。
- AI 字幕常把技术词识别错：RAG 可能识别成 RG、ROG、rap；LangChain 可能识别成 non chain、long chain；reranker 可能识别成“瑞 rank”。
- 总结时要结合分P标题和技术语境校正术语。

## 相关文件

- `scripts/check_environment.py`：检查核心流程、网页 AI 字幕、音频 ASR 和测试依赖是否可用。
- `scripts/run_bili_note.py`：一键运行元数据、字幕、评论、归档和证据索引流程。
- `scripts/extract_bilibili.py`：元数据、字幕探测、普通字幕、音频、ASR、评论抓取。
- `scripts/fetch_browser_ai_subtitles.py`：通过已登录网页播放器下载 B站 AI 字幕。
- `scripts/archive_bili_materials.py`：归档完整材料，并生成全文索引和证据索引。
- `scripts/score_bili_note.py`：按 `metadata/note_budget.json` 校验最终笔记的长度、压缩比和证据引用。
- `scripts/update_note_budget_section.py`：把预算、互动质量和信噪比评分写回 Markdown 笔记。
- `references/bilibili-api-notes.md`：接口细节和已知坑。
