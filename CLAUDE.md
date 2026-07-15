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