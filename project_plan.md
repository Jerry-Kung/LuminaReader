# LuminaReader

## 1. Project Description
LuminaReader 是一个本地优先、以阅读为中心的 AI 辅助 PDF 阅读工具。用户从"我的书架"入口页管理自己的 PDF 书籍，打开后可在页面上框选区域，通过后端 AI 接口将选中内容翻译为简体中文或解释，在侧边栏以对话气泡形式查看结果。

## 2. Page Structure
- `/` - 我的书架（网格卡片展示已上传的书籍，支持上传、排序、删除）
- `/reader/:pdf_id` - PDF 阅读主页面（左侧阅读区 + 右侧 AI 翻译面板）

## 3. Core Features
- [x] 从本地选择并打开 PDF 文件
- [x] PDF 分页渲染（PDF.js）
- [x] 翻页（上一页 / 下一页 / 跳转页码）
- [x] 缩放控制
- [x] 鼠标拖拽矩形选区
- [x] 调用后端 AI 接口翻译/解释选中区域
- [x] 侧边栏展示对话气泡组，支持多轮追问
- [x] Markdown + 数学公式渲染
- [x] AI 助手面板宽度可伸缩
- [x] Esc 键清除选区高亮
- [x] 我的书架入口页（书架卡片、上传、排序、删除）
- [ ] 书籍上传进度与拖拽上传
- [ ] 同名书籍提醒（非阻断）
- [ ] 书架空状态引导

## 4. Data Model Design

### Table: books（书架）
| Field | Type | Description |
|-------|------|-------------|
| id | string | 书籍唯一标识 |
| title | string | 书名（取自文件名） |
| file_name | string | 原始文件名 |
| file_size | number | 文件大小（字节） |
| cover_url | string | 封面图 URL |
| created_at | timestamp | 上传时间 |
| updated_at | timestamp | 最近打开时间 |
| page_count | number | 总页数 |

## 5. Backend / Third-party Integration Plan
- 后端 AI 翻译接口：通过 `VITE_API_BASE_URL` 环境变量配置
- 书架数据：后端提供 REST API（列表、上传、删除）
- 无 Supabase、Shopify、Stripe 集成需求

## 6. Development Phase Plan

### Phase 1: 核心阅读器 UI
- Goal: 搭建左右分栏布局、工具栏、PDF 渲染、选区翻译
- Deliverable: 可打开本地 PDF 并翻译的阅读器界面

### Phase 2: 对话式 AI 助手
- Goal: 将卡片从单轮问答演化为多轮对话，支持 Markdown 与公式渲染
- Deliverable: 完整的对话气泡组、追问、清空、Markdown 渲染

### Phase 3: 面板与交互优化
- Goal: AI 面板宽度可伸缩、Esc 清除选区
- Deliverable: 面板三态切换、Esc 两段式行为

### Phase 4: 我的书架入口页
- Goal: 新增书架页作为应用根页面，支持书籍管理
- Deliverable: 书架网格、上传、排序、删除、同名提醒、空状态