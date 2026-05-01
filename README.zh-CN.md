# scinotes

> 你的 Obsidian 兼容个人科研助理 — Telegram / QQ / 终端皆可,markdown 后台,LLM 驱动。

[English README](README.md) | MIT License | 状态:alpha (v0.1)

把一个 markdown 文件夹变成一个能"对话"的科研笔记本。在 Telegram 扔个论文链接 → wiki 里多一条结构化笔记。捕获想法、查询历史条目、记录实验进展 — 全在手机里完成,数据是你完全掌控的纯 `.md` 文件。

## 与众不同之处

- **Markdown 原生**。笔记是你指定目录下的 `.md` 文件。可用 Obsidian / Logseq / VS Code 打开,可 git 跟踪。无专有数据库。
- **科研专用工具**。一等公民命令:论文入库(带 BibTeX)、阅读队列、实验日志、想法捕获、研究画像追踪、撤销。
- **多模型路由**。默认走本地 Ollama 免费跑;消息加 `@claude` / `@glm` 等前缀临时切云端,只在需要时付费。账目透明。
- **MCP 编排**。可挂 Zotero / PubMed / Semantic Scholar(以及任意 MCP server)做文献检索。
- **Self-host 优先**。本机或小 VPS 都能跑。你的数据、你的 key、你的模型选择。

## 60 秒 demo

```text
你:把这篇 https://doi.org/10.1234/foo 加到阅读队列
助手:已加入 — "[2026-04-30 10:42] https://doi.org/10.1234/foo"
     ——
     ✓ reading_queue_add → [[阅读队列]]

你:摘要刚刚扔的 PDF 并入库
助手:[读 PDF → 起草摘要 → 生成 BibTeX → 写笔记]
      Citation key: smith2024spectroscopy
     ——
     ✓ read_local_pdf
     ✓ paper_ingest → [[论文笔记]] / smith2024spectroscopy

你:刚才那个入库的年份写错了,撤销
助手:已撤销。
     ——
     ✓ wiki_undo_last → [[论文笔记]] / smith2024spectroscopy 已删除
```

## 安装

需要 Python ≥ 3.10。建议装 [Ollama](https://ollama.com) 跑免费本地模型。

```bash
# 推荐 uv 安装(快、隔离、独立 binary)
uv tool install scinotes

# 或 pipx
pipx install scinotes
```

## 快速开始

```bash
# 1. 初始化 wiki
scinotes init ~/research-wiki --lang zh-CN

# 2. 编辑 init 创建的 .env
$EDITOR ~/research-wiki/.env
#   - 填 TELEGRAM_BOT_TOKEN(去 @BotFather 创建)
#   - 填 TELEGRAM_USER_ID(你的数字 ID — 问 @userinfobot)
#   - 至少配一个 LLM。纯本地:`ollama pull <model>`
#     云端:填 ANTHROPIC_API_KEY 或 GLM_API_KEY 等

# 3. 自检
scinotes doctor

# 4. 跑
scinotes run

# 没装 Telegram?先用终端模式试用:
scinotes run --frontends cli
```

## 架构

详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 文档

- [SETUP.md](SETUP.md) — 配置详解(每个 env 干嘛、如何申请各种 API key)
- [ARCHITECTURE.md](ARCHITECTURE.md) — 各模块如何协作
- [SECURITY.md](SECURITY.md) — **暴露在公网前必读**
- [CONTRIBUTING.md](CONTRIBUTING.md)

## 工具列表(LLM 可用)

| 工具 | 作用 |
|---|---|
| `wiki_query` | 全 wiki 关键词搜索 |
| `wiki_read_page` | 读单个页面 |
| `wiki_list_pages` | 按分类列页面 |
| `wiki_ingest` | 自由追加条目到指定页 |
| `wiki_lint` | 健康检查(孤岛 / 死链) |
| `wiki_memorize` | 追加到 `memory.md`(每轮对话强行加载) |
| `wiki_undo_last` | 撤销最近一次写入 |
| `paper_ingest` | 论文笔记入库(metadata + BibTeX + 摘要) |
| `reading_queue_add` / `reading_queue_pop` | 维护阅读队列 |
| `experiment_log` | 按项目记录实验进展 |
| `idea_capture` | 灵感卡片入想法库 |
| `update_research_profile` | 更新研究画像(sentinel 保护 + changelog 追加) |
| `read_local_pdf` | 本地 PDF 提取(pypdf,装了 `[ocr]` extra 后自动 OCR 兜底) |
| `read_pdf_ocr` | 强制 OCR(tesseract,需 `scinotes[ocr]` + 系统 binary) |
| `web_fetch_url` | 网页正文抓取(Jina Reader) |
| `web_search` | Brave 搜索 |
| `extract_video_subtitles` | YouTube / B 站字幕 |

外部 MCP server(自动连接,装了就用):Zotero、PubMed、Semantic Scholar。

## 周边项目

scinotes 负责科研工作流里的「笔记」层。如果想搭配其他能力,推荐:

- **[yufree/sciguideskill](https://github.com/yufree/sciguideskill)** —— 基于《现代科研指北》的 Claude Code / Desktop skill,扮演一个意见鲜明、坦诚的科研顾问。覆盖科研思维、实验设计、统计、论文写作、学术职业、认知偏差等话题。和 scinotes 在 Claude Desktop 里**天然搭配**:scinotes 帮你维护 wiki,sciguide 用立场回答你的方法学/职业类问题。

知道其它适合科研流程的小 MCP server / skill?欢迎 PR 加到这里。

## 状态 & 路线

当前 **v0.1 alpha**。核心流程能走通,有粗糙处。v0.2 计划:
- 错误信息双语
- 自动生成工具文档
- Docker compose 示例
- 测试 + CI
- 社区前端(Slack / Discord / Matrix)

## 许可

MIT。详见 [LICENSE](LICENSE)。
