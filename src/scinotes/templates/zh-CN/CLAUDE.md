# scinotes — wiki schema

本文件描述你个人科研 wiki 的结构。scinotes 与你共同读取它,理解页面如何组织。

## 层级

| 层级 | 用途 | 页面 |
|------|------|------|
| **科研** | scinotes 维护的科研产出 | 论文笔记、阅读队列、研究问题、实验日志、想法库、研究画像 |

你可以在此基础上自由添加自己的页面与层级。scinotes `wiki_list_pages` 会列出它们,即使没归到上面的分类里。

## 页面如何写入

scinotes 的科研层工具维护这些页面,结构稳定:

- `论文笔记` ← `paper_ingest`:每篇一节,含 metadata + BibTeX + 个人摘要
- `阅读队列` ← `reading_queue_add` / `reading_queue_pop`:未读 URL/DOI 的 FIFO 队列
- `研究问题` ← LLM 调 `wiki_ingest`,三档:在做 / 公开 / 已搁置
- `实验日志` ← `experiment_log`:按项目分节,每节按日期倒序追加
- `想法库` ← `idea_capture`:时间倒序的灵感卡片,带上下文 [[wikilink]]
- `研究画像` ← `update_research_profile`:研究背景速览。**按需读取**(不自动挂载),工具只动 sentinel 内的基本信息块与变更记录,自由文本节由用户自行维护

## 操作流程

### Ingest(摄入)
1. 判断归属哪个页面(可归多个)
2. 添加条目并附一句话"为什么收录"
3. 检查是否需要新增 [[交叉引用]]
4. 工具会自动向 `log.md` 追加变更记录

### Query(查询)
1. 用 `wiki_query` 搜本地相关页
2. 综合多个页面回答问题
3. 涉及 wiki 未覆盖的话题,先说明本地无覆盖,可选外部检索

### Lint(健康检查)
- **死链**:外部 URL 是否还可访问
- **孤岛**:有没有页面完全没被其他页面引用
- **时效**:基于特定时间数据的结论是否过期
- **交叉引用完整性**:相关页面之间是否互相 [[wikilink]]

## 文件清单

- `CLAUDE.md`(本文件)— Schema
- `log.md` — 变更记录(append-only)
- `memory.md` — 长期事实,每次对话自动加载
- `<page>.md` — wiki 正文
