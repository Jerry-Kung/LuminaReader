# LuminaReader

> 本地优先、以阅读为中心的 AI 辅助 PDF 阅读工具。

LuminaReader 是一个纯前端 PDF 阅读器，核心闭环简单直接：打开本地 PDF → 框选区域 → 选择 AI 任务（翻译 / 解释）→ 侧边栏查看结果。不上传文件、不需要登录，打开即用。

---

## 技术栈

| 类别       | 选型                                                         |
| ---------- | ------------------------------------------------------------ |
| 框架       | React 19 + TypeScript                                        |
| 构建工具   | Vite 8                                                       |
| 样式方案   | TailwindCSS 3                                                |
| PDF 渲染   | PDF.js (`pdfjs-dist`)                                        |
| 路由       | React Router 7                                               |
| 图标       | Remix Icon (CDN) + Font Awesome (CDN)                        |
| 后端 API   | 通过 `VITE_API_BASE_URL` 环境变量配置，无后端时自动走模拟模式 |

---

## 项目结构

```
src/
├── services/
│   └── api.ts                       # API 调用层：封装 /api/v1/run 调用、错误信封、taskType 路由、mock 回退
├── hooks/
│   └── usePDF.ts                    # PDF 加载、翻页、缩放等状态管理的自定义 Hook
├── pages/
│   └── reader/
│       ├── page.tsx                 # 主阅读页面，组合所有子组件 & 管理全局状态（含 activeTaskType）
│       └── components/
│           ├── Toolbar.tsx           # 顶部工具栏：打开文件、翻页、缩放、Translate/Explain 段控件、Run 触发
│           ├── PDFViewer.tsx         # PDF 渲染与鼠标拖拽选区交互
│           └── AIAssistantPanel.tsx  # 右侧 AI 助手面板：按 task 类型显示标签色，支持复制
├── router/
│   ├── index.ts                     # 路由入口（已封装 AppRoutes）
│   └── config.tsx                   # 路由配置表
├── App.tsx                          # 应用根组件，挂载 BrowserRouter
├── main.tsx                         # 页面入口
└── index.css                        # 全局样式 & Tailwind 指令
```

---

## 核心功能

### 1. 本地 PDF 打开与渲染

- 用户通过工具栏「Open PDF」按钮选择本地 PDF 文件
- 文件通过 `FileReader` 读取为 `ArrayBuffer`，交给 PDF.js 在前端渲染
- **文件全程不上传服务器**，所有解析在浏览器本地完成

### 2. 翻页与缩放

- **翻页**：工具栏提供上/下一页按钮，支持在页码输入框中键入数字后 Enter 跳转
- **缩放**：+/- 按钮逐级调整，范围 40% ~ 300%，步长 0.2

### 3. 鼠标拖拽矩形选区

- 在 PDF 画布上按住鼠标拖拽即可绘制琥珀色选区框
- 选区坐标基于 canvas 坐标系统计算，自动适配缩放比例
- 最小选区阈值 10px × 10px，防止误触
- 选中区域在右侧以百分比定位 overlay 展示

### 4. AI 任务（翻译 / 解释）

- 选中区域后，先在工具栏的段控件中选择 **Translate** 或 **Explain**（默认 Translate）
- 点击 **Run** 按钮触发；前端将选中区域对应的 canvas 部分裁剪、导出为 base64 PNG
- 调用 service 层 `translateSelection(selection, image, { targetLang, taskType })`，发送到后端 `/api/v1/run`
- 返回结果在右侧 AI 助手面板顶部追加展示

### 5. AI 结果展示

- 右侧 340px 宽固定面板，显示所有历史 AI 卡片
- 每张卡片含截图缩略图 + 任务类型标签（Translate 琥珀色 / Explain teal）+ 输出文本 + 复制按钮
- hover 时显示复制按钮，一键复制到剪贴板
- 多轮结果按时间倒序排列

### 6. 状态覆盖

| 状态       | 处理方式                                                     |
| ---------- | ------------------------------------------------------------ |
| 无文件     | PDF 区域显示空状态提示，指引用户打开文件                      |
| 加载中     | PDF 区域显示 spinner + "Loading PDF..." 文案                  |
| 加载错误   | 显示红色错误信息（如无效 PDF 文件）                           |
| AI 工作中  | Run 按钮变为 loading 态（文案随 task 切换），侧边栏显示 spinner |
| AI 错误    | 侧边栏显示红色错误卡片（含错误码格式 `[CODE] message`）         |
| 无 AI 结果 | 侧边栏显示空状态占位                                         |

---

## 架构设计

### 数据流

```
用户操作                 组件状态                   API/服务
┌──────────┐    ┌─────────────────────┐    ┌──────────────────┐
│ 选择文件  │───▶│ usePDF Hook          │───▶│ FileReader       │
│          │    │ (pdfDoc, page, scale)│    │ → PDF.js 解析    │
└──────────┘    └─────────────────────┘    └──────────────────┘

┌──────────┐    ┌─────────────────────┐    ┌──────────────────┐
│ 拖拽选区  │───▶│ ReaderPage state     │    │                  │
│          │    │ (selectedArea)       │    │                  │
└──────────┘    └─────────────────────┘    └──────────────────┘

┌──────────┐    ┌─────────────────────┐    ┌──────────────────┐
│ 选择任务  │───▶│ ReaderPage           │───▶│ api.ts           │
│ + Run    │    │ handleAIRequest(t)   │    │ translateSelect()│
│          │    │ → canvas 截图        │    │ → /api/v1/run    │
│          │    │ → 更新 results[]     │    │   或 mock 回退   │
└──────────┘    └─────────────────────┘    └──────────────────┘
```

### 组件层级

```
<ReaderPage>                         ← 状态管理中心（含 activeTaskType）
├── <Toolbar />                      ← 纯展示组件，提供 task 段控件与 Run 触发
├── <PDFViewer />                    ← PDF 渲染 + 鼠标选区交互
└── <AIAssistantPanel />             ← AI 卡片列表（按 task 类型上色）
```

所有业务逻辑集中在 `ReaderPage`（page.tsx），子组件保持纯粹无状态。PDF 相关状态通过 `usePDF` 自定义 Hook 封装，AI API 调用通过 `src/services/api.ts` 封装。

---

## API 接口设计

### 调用入口

当配置了 `VITE_API_BASE_URL` 时，前端调用：

```
POST {VITE_API_BASE_URL}/api/v1/run
Content-Type: application/json

{
  "task_type": "translate" | "explain",
  "selection": {
    "pdf_id": null,
    "page": 1,
    "x": 0, "y": 0, "w": 100, "h": 80,
    "dpi": 144
  },
  "image": {
    "mime": "image/png",
    "data": "<base64 不含 data: 前缀>",
    "width": 200, "height": 160
  },
  "options": { "target_lang": "zh-CN" }
}

Response（成功）:
{
  "ok": true,
  "data": {
    "text": "AI 输出文本",
    "meta": {
      "request_id": "req_...",
      "model": "gpt-4o",
      "latency_ms": 1234,
      "task_type": "translate",
      "usage": { "prompt_tokens": ..., "completion_tokens": ..., "total_tokens": ... }
    }
  }
}

Response（错误）:
{
  "ok": false,
  "error": { "code": "UNSUPPORTED_TASK", "message": "...", "request_id": "req_..." }
}
```

完整契约见 `../claude_docs/api-contract.md §4`。错误码映射后由 `TranslateApiError`（含 `code` / `requestId` / `httpStatus`）抛出，UI 以 `[CODE] message` 形式呈现。

### 模拟模式

未配置 `VITE_API_BASE_URL` 时自动启用模拟模式，按 `taskType` 返回不同预设中文文案，并模拟 0.8~1.5 秒网络延迟，方便本地原型演示。

---

## 环境变量

在项目根目录创建 `.env` 文件：

```env
VITE_API_BASE_URL=https://your-api-server.com
```

| 变量名               | 说明             | 必填 |
| -------------------- | ---------------- | ---- |
| `VITE_API_BASE_URL`  | 后端 API 基地址   | 否   |

---

## 快速开始

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build

# 预览生产构建
npm run preview
```

---

## 当前阶段边界（V1.0.1）

当前阶段已交付：翻译 + 解释两类 AI 任务。明确不做以下内容（参见 `../claude_docs/v1/v1.0.1/requirements.md`）：

- 账号登录、多用户、权限
- 书库 / 项目管理 / 多 PDF 管理
- 笔记、标注、历史记录持久化（关闭页面历史会丢失）
- 多轮对话 / 追问（卡片仍是一问一答）
- 第三种及以上 AI 任务（问答、总结等）
- 模型配置界面

---

## 开发路线图

| 阶段    | 目标                                                            | 状态 |
| ------- | --------------------------------------------------------------- | ---- |
| V0      | 核心 UI 框架：布局、工具栏、PDF 渲染、选区拖拽、翻译闭环         | ✅    |
| V1.0.0  | 阅读器交互打磨（滚轮翻页、Ctrl 缩放、Select 模式、Esc 退出）       | ✅    |
| V1.0.1  | AI 多任务：Translate / Explain 段控件、AI 助手面板类型标签       | ✅（前端） |