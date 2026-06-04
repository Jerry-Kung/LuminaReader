This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 1. 项目概述

- **项目名**：LuminaReader，一款面向PDF书籍深度阅读的 AI 辅助阅读工作台。
- **定位**：本地优先、模型可配置、以书籍 Project 为组织单位的 AI 阅读助手
- **完整愿景与功能规划**：见 `README.md`
- **当前阶段**：项目 V1.1 设计与开发阶段，遵循“小步快跑”式开发原则。

## 2. 工作规范

- 使用简体中文回答问题、编写文档
- 新版本的需求分析、模块设计、任务规划等重量级更新，讨论明确后归档到./claude_docs目录。轻量级的代码改动/bug修复可以直接执行，不写文档
- 涉及整体架构/核心数据结构/跨模块接口契约/前后端配合等重要变更行为的改动，请同步更新./claude_docs中的相关文档
- 默认不进行全量文档阅读，仅阅读与当前任务直接相关的项目文档，默认不阅读历史版本归档文件
- 如有必要更新CLAUDE.md与README.md等核心文档，遵守最小化更新原则，不得添加任务无关的冗余内容
- 小规模的代码改动（更新范围不超过100行代码/3个文件，不涉及重要的前端UI/数据结构/API/架构改动）由你直接执行。中等规模及以上的设计与开发工作请转交给readdy.ai和Cursor（参考第5和第6节内容）

## 3. 核心文档

- README.md 项目背景/愿景/基本规划，未经明确要求，请勿擅自修改
- CLAUDE.md claude项目规范，未经明确要求，请勿擅自修改
- ./claude_docs/ 项目文档目录，正式、稳定、长期维护的设计文档
**目录结构**：见 `claude_docs/README.md`，阅读该文档以同步获取写入说明

- ./chat_docs/ Vibe Coding聊天过程中产生的过程中间文档
**目录结构**：见 `chat_docs/README.md`，阅读该文档以同步获取写入说明
**生命周期**：达成结论后，**有价值的内容应被提炼并迁移到 `claude_docs/`**，迁移过后及时清除原始文档。

## 4. 技术栈与运行形态

### 4.1 锁定的技术栈

| 层 | 技术 |
|---|---|
| 前端框架 | React + TypeScript |
| 前端构建 | Vite |
| 后端语言 | Python（版本建议3.12）|
| 后端框架 | 由设计文档确定（推荐 FastAPI） |
| 数据存储 | SQLite + 文件系统 |
| PDF 渲染 | PDF.js |
| LLM 调用 | 通过自定义 Provider 抽象层接入 Anthropic / OpenAI 等 |
| 容器化 | Docker + Docker Compose（后续阶段引入） |

**未经用户同意，不得替换上述任何一项核心技术选型。**

### 4.2 运行形态

- **当前阶段**：在本地 Windows 操作系统上运行；前后端在同一仓库内并行开发。
- **目标形态**：支持通过 `docker compose up` 一键部署运行整个应用。
- **跨平台要求**：所有路径处理、shell 调用、文件操作必须考虑 Windows 兼容性；不得硬编码 Unix 风格路径。
- **路径约定**：项目内部统一使用相对路径或通过配置注入的绝对路径，禁止硬编码用户目录。

### 4.3 单仓库结构

前后端代码在同一个 Git 仓库内，**目录树结构由 `claude_docs/project-structure.md` 定义**，不得自行偏离。

## 5. 外部协作：readdy.ai（前端 UI 设计）

- 涉及前端页面及 UI 的重要设计，一般交由 readdy.ai 执行；用户会在输入中明确要求时启用。
- readdy.ai 交付物为前端工程代码（统一上传到 `reader-page` 分支），通过 git 方式合入主仓库。
- 交付给 readdy.ai 的 Prompt 必须在 `./claude_docs/prompts/` 中归档。
- **详细规则**：`./claude_docs/readdy-collaboration.md`（代码同步规则、Prompt 编写规范、长度上限等全部细节）。涉及 readdy.ai 工作前必读。

## 6. 外部协作：Cursor（代码级开发）

- 后端及其他代码级开发任务交由 Cursor 按文档执行；Claude Code 负责将需求拆解为 Task 文档。
- 每个 Task 独立成目录，置于 `claude_docs/<版本>/tasks/`（如 `claude_docs/v0/tasks/`），Cursor 只读 `claude_docs/`。
- 目录内含：`README.md`（Task 总纲：目标、范围、子任务索引、整体验收）、若干 `NN-*.md`子任务文档（目标/涉及文件/实现要点/交付边界/测试用例/验收标准）、一份 `prompt.md`（启动提示词）。
- 每个 Task 尽量只交付一个独立功能点；版本过大时拆为多个顺序 Task，依赖关系在 `tasks/README.md` 标明。
- 每个 Task 只配一份 `prompt.md`（不为子任务各配一份），用于指示 Cursor 先读文档再编码。
- 新增/删除 Task 目录后，同步更新 `tasks/README.md` 的 Task 清单。