# scripts/

项目本地启动与辅助脚本目录。每个脚本同时提供 `.ps1`（Windows PowerShell）与 `.sh`（Bash）两份，保持跨平台一致。

> 完整的配置项语义、端口冲突应对、故障速查见 `../claude_docs/setup-and-run.md`。

---

## 前置依赖

| 依赖 | 版本 |
|---|---|
| Node.js | ≥ 20 LTS |
| npm | 随 Node 自带 |
| Python | 3.12.x |
| uv | ≥ 0.4 |

---

## 脚本清单

| 脚本 | 用途 | 状态 |
|---|---|---|
| `dev.{ps1,sh}` | **一键启动前后端**（合流输出，Ctrl+C 同时停） | ✅ 可用 |
| `dev-frontend.{ps1,sh}` | 单独启动前端 Vite 开发服务器 | ✅ 可用 |
| `dev-backend.{ps1,sh}` | 单独启动后端 FastAPI（uvicorn + reload） | ✅ 可用 |
| `test-backend.{ps1,sh}` | 运行后端测试（pytest） | ✅ 可用 |

所有脚本均通过脚本自身位置推导仓库根，不依赖当前工作目录，可从任意位置调用。

---

## 首次准备（一次性）

```powershell
# 在仓库根目录执行

# 后端
cd backend
uv sync
Copy-Item .env.example .env       # 填入 OPENAI_API_KEY 等真实配置
cd ..

# 前端
cd frontend
npm install
Copy-Item .env.example .env       # 默认指向 http://127.0.0.1:18086
cd ..
```

Bash 用户把 `Copy-Item` 替换为 `cp` 即可。

---

## 启动

### 一键启动（推荐，单窗口）

**Windows PowerShell**：
```powershell
.\scripts\dev.ps1
```

**Bash / macOS / Linux**：
```bash
./scripts/dev.sh
```

前后端在同一窗口启动，日志带 `[backend ]` / `[frontend]` 前缀合流输出；按一次 Ctrl+C 同时停掉两者（脚本会递归回收 uvicorn / node 子进程，避免残留占用端口）。

启动成功后，浏览器访问 **http://localhost:3000**，在阅读器中框选区域即可调用后端 `/api/v1/run`。

### 分窗口启动（备用）

需要把前后端日志分窗口观察、或只想拉起其中一个时使用：

**Windows PowerShell**：
```powershell
.\scripts\dev-backend.ps1         # 后端：http://127.0.0.1:18086
.\scripts\dev-frontend.ps1        # 前端：http://localhost:3000
```

**Bash / macOS / Linux**：
```bash
./scripts/dev-backend.sh
./scripts/dev-frontend.sh
```

### 后端冒烟验证

```powershell
curl http://127.0.0.1:18086/api/v1/health
```

预期返回 `{"ok":true,"data":{"service":"lumina-backend","provider_ready":true,...}}`。

---

## 测试

```powershell
.\scripts\test-backend.ps1        # 等价 cd backend && uv run pytest
```

---

## 端口

| 服务 | 默认端口 | 来源 |
|---|---|---|
| 前端 Vite dev | 3000 | `frontend/vite.config.ts` 中 `server.port` |
| 后端 FastAPI | 18086 | `backend/.env` 的 `PORT` |

端口冲突应对：参见 `../claude_docs/setup-and-run.md §2.1`。
