# LuminaReader

## 1. Project Description
LuminaReader 是一个本地优先、以阅读为中心的 AI 辅助 PDF 阅读工具。用户打开本地 PDF 文件，在页面上框选区域，通过后端 AI 接口将选中内容翻译为简体中文，在侧边栏查看译文。

## 2. Page Structure
- `/` - PDF 阅读主页面（左侧阅读区 + 右侧 AI 翻译面板）

## 3. Core Features
- [ ] 从本地选择并打开 PDF 文件
- [ ] PDF 分页渲染（PDF.js）
- [ ] 翻页（上一页 / 下一页 / 跳转页码）
- [ ] 缩放控制
- [ ] 鼠标拖拽矩形选区
- [ ] 调用后端 AI 接口翻译选中区域
- [ ] 侧边栏展示翻译结果，支持复制
- [ ] 加载中 / 出错提示状态
- [ ] API 调用封装为独立 service 层
- [ ] 后端地址通过环境变量配置

## 4. Data Model Design
V0 阶段无后端数据存储需求，纯前端工具。

## 5. Backend / Third-party Integration Plan
- 后端 AI 翻译接口：通过 `VITE_API_BASE_URL` 环境变量配置，POST 请求发送选区截图 + 目标语言，返回翻译文本
- 无 Supabase、Shopify、Stripe 集成需求

## 6. Development Phase Plan

### Phase 1: 核心 UI 框架搭建
- Goal: 搭建左右分栏布局、工具栏、PDF 渲染基础
- Deliverable: 可打开本地 PDF 并分页渲染的阅读器界面

### Phase 2: 选区与翻译功能
- Goal: 实现矩形选区拖拽、调用翻译 API、结果展示
- Deliverable: 完整的「选择 → 翻译 → 查看结果」闭环

### Phase 3: 细节打磨
- Goal: 加载/错误/空状态、复制功能、缩放优化等
- Deliverable: 交互完整体验打磨