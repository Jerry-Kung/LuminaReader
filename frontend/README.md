# LuminaReader

> 本地优先、以阅读为中心的 AI 辅助 PDF 阅读工具。

LuminaReader 是一个纯前端 PDF 阅读器，核心闭环简单直接：打开本地 PDF → 框选区域 → 交给 AI 翻译成简体中文 → 侧边栏查看结果。不上传文件、不需要登录，打开即用。

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
│   └── api.ts                       # API 调用层，封装翻译请求与模拟回退
├── hooks/
│   └── usePDF.ts                    # PDF 加载、翻页、缩放等状态管理的自定义 Hook
├── pages/
│   └── reader/
│       ├── page.tsx                 # 主阅读页面，组合所有子组件 & 管理全局状态
│       └── components/
│           ├── Toolbar.tsx           # 顶部工具栏：打开文件、翻页、缩放、翻译触发
│           ├── PDFViewer.tsx         # PDF 渲染与鼠标拖拽选区交互
│           └── TranslationPanel.tsx  # 右侧翻译结果面板，支持复制
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

### 4. AI 翻译

- 选中区域后点击「Translate」按钮
- 前端将选中区域对应的 canvas 部分裁剪、导出为 base64 PNG
- 调用 API service 层 `translateSelection()` 发送到后端接口
- 返回译文后在右侧面板顶部追加展示

### 5. 翻译结果展示

- 右侧 340px 宽固定面板，显示所有历史翻译结果
- 每条结果以卡片形式展示，hover 时出现复制按钮
- 支持一键复制到剪贴板
- 多轮翻译结果按时间倒序排列

### 6. 状态覆盖

| 状态       | 处理方式                                                     |
| ---------- | ------------------------------------------------------------ |
| 无文件     | PDF 区域显示空状态提示，指引用户打开文件                      |
| 加载中     | PDF 区域显示 spinner + "Loading PDF..." 文案                  |
| 加载错误   | 显示红色错误信息（如无效 PDF 文件）                           |
| 翻译中     | 翻译按钮变为 loading 态，侧边栏显示 spinner                   |
| 翻译错误   | 侧边栏显示红色错误卡片                                       |
| 无翻译结果 | 侧边栏显示空状态占位                                         |

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
│ 点击翻译  │───▶│ ReaderPage           │───▶│ api.ts           │
│          │    │ handleTranslate()    │    │ translateSelect() │
│          │    │ → canvas 截图        │    │ → fetch/mock     │
│          │    │ → 更新 results[]     │    │ → translated_text │
└──────────┘    └─────────────────────┘    └──────────────────┘
```

### 组件层级

```
<ReaderPage>                         ← 状态管理中心
├── <Toolbar />                      ← 纯展示组件，通过 props 接收回调
├── <PDFViewer />                    ← PDF 渲染 + 鼠标选区交互
└── <TranslationPanel />             ← 翻译结果列表展示
```

所有业务逻辑集中在 `ReaderPage`（page.tsx），子组件保持纯粹无状态。PDF 相关状态通过 `usePDF` 自定义 Hook 封装，翻译 API 调用通过 `src/services/api.ts` 封装。

---

## API 接口设计

### 翻译接口

当配置了 `VITE_API_BASE_URL` 时，前端调用：

```
POST {VITE_API_BASE_URL}/api/translate
Content-Type: application/json

{
  "image": "data:image/png;base64,...",   // 选区截图 base64
  "target_language": "zh-CN"              // 目标语言
}

Response:
{
  "translated_text": "翻译后的中文文本"
}
```

### 模拟模式

未配置 `VITE_API_BASE_URL` 时自动启用模拟模式，返回预设中文文本并模拟 0.8~1.5 秒网络延迟，方便本地原型演示。

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

## V0 阶段边界

当前版本（V0）是技术验证原型，明确不做以下内容：

- 账号登录、多用户、权限
- 书库 / 项目管理 / 多 PDF 管理
- 笔记、标注、历史记录保存
- 多轮对话 / 追问
- 翻译以外的 AI 能力（解释、问答、总结等）
- 模型配置界面

---

## 开发路线图

| 阶段   | 目标                               | 状态 |
| ------ | ---------------------------------- | ---- |
| Phase 1 | 核心 UI 框架：布局、工具栏、PDF 渲染 | ✅    |
| Phase 2 | 选区拖拽 + 翻译功能 + 结果展示      | ✅    |
| Phase 3 | 体验打磨：状态覆盖、复制、缩放优化   | ✅    |