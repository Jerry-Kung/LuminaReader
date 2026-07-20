"""V1.2.3 跑批编排：快照 / 串行跑批 / 单章失败续跑 / 取消 / 重建 / 孤儿恢复。"""

import asyncio
import json

import pytest

from lumina.db.engine import get_connection
from lumina.db.models import get_memory_meta, list_memory_units
from lumina.memory import service
from lumina.pdftext.service import run_extraction_sync
from lumina.projects.manager import auto_create_project
from lumina.providers.base import LLMRequest, LLMResponse, Provider, ProviderUpstreamError

from tests.test_pdftext.pdf_fixtures import make_text_pdf

PAGES = [f"page {i} body text " * 10 for i in range(1, 9)]  # 8 页文本书

UNIT_JSON = json.dumps(
    {"summary": "## 要点\n- x", "concepts": [{"term": "t", "definition": "d", "page": 1}]},
    ensure_ascii=False,
)


class ScriptedProvider(Provider):
    """按调用序返回脚本化响应；"BOOM" 表示该次调用抛上游错误。"""

    name = "scripted"

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls: list[LLMRequest] = []

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        text = self.script.pop(0) if self.script else UNIT_JSON
        if text == "BOOM":
            raise ProviderUpstreamError("upstream 500")
        return LLMResponse(text=text, model="fake")

    async def invoke_stream(self, req):
        raise NotImplementedError
        yield  # pragma: no cover

    async def health_check(self) -> bool:
        return True


def _make_book(data_root):
    created = auto_create_project(make_text_pdf(PAGES), "book.pdf")
    run_extraction_sync(created.project_id, created.pdf_id)
    return created


async def _wait_done(project_id, pdf_id, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        state = service.read_state(project_id, pdf_id)
        if state.meta is not None and state.meta.status != service.STATUS_RUNNING:
            return state
        await asyncio.sleep(0.02)
    raise AssertionError("batch did not finish in time")


@pytest.mark.asyncio
async def test_build_happy_path_ready(data_root):
    created = _make_book(data_root)
    provider = ScriptedProvider([UNIT_JSON, "# 全书总结"])  # 1 单元 + 1 总结
    state, started = service.start_build(created.project_id, created.pdf_id, provider)
    assert started is True and state.meta.status == service.STATUS_RUNNING
    final = await _wait_done(created.project_id, created.pdf_id)
    assert final.meta.status == service.STATUS_READY
    assert final.meta.book_summary == "# 全书总结"
    assert final.meta.unit_done == final.meta.unit_total >= 1
    units = final.units
    assert all(u.status == "ok" and u.summary for u in units)
    # 概念已落库
    conn = get_connection(created.project_id)
    n = conn.execute("SELECT COUNT(*) FROM memory_concepts WHERE pdf_id = ?", (created.pdf_id,)).fetchone()[0]
    assert n >= 1


@pytest.mark.asyncio
async def test_book_summary_failure_partial_then_retry(data_root):
    created = _make_book(data_root)
    provider = ScriptedProvider([UNIT_JSON, "BOOM"])  # 单元成功、总结失败
    service.start_build(created.project_id, created.pdf_id, provider)
    final = await _wait_done(created.project_id, created.pdf_id)
    assert final.meta.status == service.STATUS_PARTIAL
    assert "总结" in (final.meta.error or "")
    assert all(u.status == "ok" for u in final.units)

    # 再次 build：pending 为空，直接重试总结（仅 1 次调用）
    provider2 = ScriptedProvider(["# 总结"])
    _, started = service.start_build(created.project_id, created.pdf_id, provider2)
    assert started is True
    final2 = await _wait_done(created.project_id, created.pdf_id)
    assert final2.meta.status == service.STATUS_READY
    assert final2.meta.book_summary == "# 总结"
    assert len(provider2.calls) == 1


@pytest.mark.asyncio
async def test_unit_failure_partial_then_resume(data_root, monkeypatch):
    # 预算压小 → 8 页 / 每单元 ~2 页 → 多单元；首单元失败其余继续
    from lumina.config import get_settings
    monkeypatch.setattr(get_settings(), "lumina_memory_unit_max_chars", 500, raising=False)
    created = _make_book(data_root)
    provider = ScriptedProvider(["BOOM"])  # 第 1 单元失败，其余默认 UNIT_JSON 成功
    service.start_build(created.project_id, created.pdf_id, provider)
    final = await _wait_done(created.project_id, created.pdf_id)
    assert final.meta.status == service.STATUS_PARTIAL
    failed = [u for u in final.units if u.status == "failed"]
    assert len(failed) == 1 and final.meta.unit_done == final.meta.unit_total - 1

    # 续跑：只补失败单元（1 次单元调用 + 1 次总结调用）
    provider2 = ScriptedProvider([UNIT_JSON, "# 总结"])
    state, started = service.start_build(created.project_id, created.pdf_id, provider2)
    assert started is True
    final2 = await _wait_done(created.project_id, created.pdf_id)
    assert final2.meta.status == service.STATUS_READY
    assert len(provider2.calls) == 2


@pytest.mark.asyncio
async def test_build_idempotent_while_running(data_root):
    created = _make_book(data_root)

    class SlowProvider(ScriptedProvider):
        async def invoke(self, req):
            await asyncio.sleep(0.2)
            return await super().invoke(req)

    provider = SlowProvider([UNIT_JSON, "# 总结"])
    _, started1 = service.start_build(created.project_id, created.pdf_id, provider)
    _, started2 = service.start_build(created.project_id, created.pdf_id, provider)
    assert started1 is True and started2 is False
    await _wait_done(created.project_id, created.pdf_id)


@pytest.mark.asyncio
async def test_build_when_ready_raises(data_root):
    created = _make_book(data_root)
    service.start_build(created.project_id, created.pdf_id, ScriptedProvider([UNIT_JSON, "# 总结"]))
    await _wait_done(created.project_id, created.pdf_id)
    with pytest.raises(service.MemoryAlreadyReadyError):
        service.start_build(created.project_id, created.pdf_id, ScriptedProvider([]))


@pytest.mark.asyncio
async def test_rebuild_replaces_old(data_root):
    created = _make_book(data_root)
    service.start_build(created.project_id, created.pdf_id, ScriptedProvider([UNIT_JSON, "# 旧总结"]))
    first = await _wait_done(created.project_id, created.pdf_id)
    old_unit_ids = {u.id for u in first.units}
    service.start_rebuild(created.project_id, created.pdf_id, ScriptedProvider([UNIT_JSON, "# 新总结"]))
    second = await _wait_done(created.project_id, created.pdf_id)
    assert second.meta.book_summary == "# 新总结"
    assert {u.id for u in second.units}.isdisjoint(old_unit_ids)


@pytest.mark.asyncio
async def test_cancel_cooperative(data_root, monkeypatch):
    from lumina.config import get_settings
    monkeypatch.setattr(get_settings(), "lumina_memory_unit_max_chars", 500, raising=False)
    created = _make_book(data_root)
    started_first_call = asyncio.Event()

    class GatedProvider(ScriptedProvider):
        async def invoke(self, req):
            started_first_call.set()
            await asyncio.sleep(0.1)
            return await super().invoke(req)

    provider = GatedProvider([])
    service.start_build(created.project_id, created.pdf_id, provider)
    await asyncio.wait_for(started_first_call.wait(), 2)
    service.request_cancel(created.project_id, created.pdf_id)
    final = await _wait_done(created.project_id, created.pdf_id)
    assert final.meta.status == service.STATUS_PARTIAL
    assert "取消" in (final.meta.error or "")
    # 至少留有 pending 单元（未跑完即停）
    assert any(u.status != "ok" for u in final.units)


@pytest.mark.asyncio
async def test_unavailable_without_text(data_root):
    created = auto_create_project(make_text_pdf(PAGES), "noext.pdf")  # 未提取
    with pytest.raises(service.MemoryUnavailableError):
        service.start_build(created.project_id, created.pdf_id, ScriptedProvider([]))
    with pytest.raises(service.MemoryUnavailableError):
        service.estimate(created.project_id, created.pdf_id)


def test_estimate_full_and_remaining(data_root):
    created = _make_book(data_root)
    est = service.estimate(created.project_id, created.pdf_id)
    assert est["scope"] == "full" and est["unit_count"] >= 1
    assert est["estimated_input_tokens"] > 0 and est["estimated_output_tokens"] > 0
    assert est["currency"] == "USD"


@pytest.mark.asyncio
async def test_estimate_remaining_after_partial(data_root, monkeypatch):
    from lumina.config import get_settings
    monkeypatch.setattr(get_settings(), "lumina_memory_unit_max_chars", 500, raising=False)
    created = _make_book(data_root)
    service.start_build(created.project_id, created.pdf_id, ScriptedProvider(["BOOM"]))
    await _wait_done(created.project_id, created.pdf_id)
    est = service.estimate(created.project_id, created.pdf_id)
    assert est["scope"] == "remaining" and est["unit_count"] == 1


@pytest.mark.asyncio
async def test_orphan_running_recovered(data_root):
    created = _make_book(data_root)
    service.start_build(created.project_id, created.pdf_id, ScriptedProvider([UNIT_JSON, "# 总结"]))
    await _wait_done(created.project_id, created.pdf_id)
    # 人为把 meta 打回 running 模拟进程崩溃残留
    conn = get_connection(created.project_id)
    conn.execute("UPDATE memory_meta SET status = 'running' WHERE pdf_id = ?", (created.pdf_id,))
    service.recover_orphan_running()
    meta = get_memory_meta(conn, created.pdf_id)
    assert meta.status == service.STATUS_PARTIAL and "中断" in (meta.error or "")


@pytest.mark.asyncio
async def test_toc_changed_flag(data_root):
    created = _make_book(data_root)
    service.start_build(created.project_id, created.pdf_id, ScriptedProvider([UNIT_JSON, "# 总结"]))
    await _wait_done(created.project_id, created.pdf_id)
    state = service.read_state(created.project_id, created.pdf_id)
    assert state.toc_changed is False
    # 模拟目录重跑：pdf_toc_meta.updated_at 变化（无目录书快照 toc_updated_at=None，
    # 目录出现即视为变更）
    conn = get_connection(created.project_id)
    conn.execute(
        "INSERT OR REPLACE INTO pdf_toc_meta (pdf_id, status, source, chapter_count, updated_at, error) "
        "VALUES (?, 'ready', 'heuristic', 3, 999999, NULL)",
        (created.pdf_id,),
    )
    state2 = service.read_state(created.project_id, created.pdf_id)
    assert state2.toc_changed is True
