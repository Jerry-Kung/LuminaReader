# LuminaReader 后端

V0 后端：FastAPI + Python 3.12，包名 `lumina`。

## 前置依赖

- Python 3.12.x
- [uv](https://docs.astral.sh/uv/) ≥ 0.4

## 首次准备

```powershell
cd backend
uv sync
Copy-Item .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY 等
```

## 启动

在仓库根目录：

```powershell
.\scripts\dev-backend.ps1
```

或在本目录：

```powershell
uv run uvicorn lumina.main:app --host 127.0.0.1 --port 18086 --reload
```

## 测试

```powershell
# 仓库根目录
.\scripts\test-backend.ps1

# 或本目录
uv run pytest
```

完整配置与脚本说明见 [`../claude_docs/setup-and-run.md`](../claude_docs/setup-and-run.md)。
