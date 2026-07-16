from lumina.db.engine import get_connection
from lumina.db.models import PdfTextMetaRow, replace_pdf_text_pages, upsert_pdf_text_meta
from lumina.pdftext.context import build_context_block
from lumina.pdftext.service import (
    STATUS_FAILED,
    STATUS_NONE,
    STATUS_OK,
    read_status,
    run_extraction_sync,
)
from lumina.projects.manager import auto_create_project
from lumina.projects.paths import project_pdf_path

from tests.test_pdftext.pdf_fixtures import make_text_pdf

TEXT_PAGES = [
    f"Page {i} body text long enough to count as textual content for tests."
    for i in range(1, 11)
]


def _create_project(pages: list[str], name: str = "ctxbook.pdf"):
    return auto_create_project(make_text_pdf(pages), name)


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------


def test_read_status_none_for_legacy_project(data_root):
    created = _create_project(TEXT_PAGES)
    meta = read_status(created.project_id, created.pdf_id)
    assert meta.status == STATUS_NONE


def test_run_extraction_sync_ok_and_idempotent(data_root):
    created = _create_project(TEXT_PAGES)
    meta = run_extraction_sync(created.project_id, created.pdf_id)
    assert meta.status == STATUS_OK
    assert meta.page_count == 10
    assert meta.textual_page_count == 10
    assert (meta.char_count or 0) > 0

    conn = get_connection(created.project_id)
    count = conn.execute("SELECT COUNT(*) FROM pdf_text_pages").fetchone()[0]
    assert count == 10

    # 重跑幂等：不产生重复行
    meta2 = run_extraction_sync(created.project_id, created.pdf_id)
    assert meta2.status == STATUS_OK
    count = conn.execute("SELECT COUNT(*) FROM pdf_text_pages").fetchone()[0]
    assert count == 10
    assert read_status(created.project_id, created.pdf_id).status == STATUS_OK


def test_run_extraction_sync_failed_on_corrupt_pdf(data_root):
    created = auto_create_project(b"%PDF-1.4 corrupt body", "broken.pdf")
    meta = run_extraction_sync(created.project_id, created.pdf_id)
    assert meta.status == STATUS_FAILED
    assert meta.error

    # 修好文件后重试可恢复
    project_pdf_path(created.project_id).write_bytes(make_text_pdf(TEXT_PAGES))
    meta = run_extraction_sync(created.project_id, created.pdf_id)
    assert meta.status == STATUS_OK


# ---------------------------------------------------------------------------
# context block
# ---------------------------------------------------------------------------


def _seed_text(project_id: str, pdf_id: str, pages: list[str], status: str = "ok"):
    conn = get_connection(project_id)
    replace_pdf_text_pages(conn, pdf_id, pages)
    upsert_pdf_text_meta(
        conn,
        PdfTextMetaRow(
            pdf_id=pdf_id,
            status=status,
            page_count=len(pages),
            textual_page_count=len(pages),
            char_count=sum(len(t) for t in pages),
        ),
    )


def test_context_block_window_and_order(data_root, pdf_project):
    pages = [f"page-{i} " + "x" * 30 for i in range(1, 11)]
    _seed_text(pdf_project.project_id, pdf_project.pdf_id, pages)
    block = build_context_block(
        pdf_project.project_id,
        pdf_project.pdf_id,
        5,
        5,
        window_pages=2,
        max_chars=100_000,
    )
    assert block is not None
    assert "pages 3-7" in block
    for i in (3, 4, 5, 6, 7):
        assert f"[Page {i}]\npage-{i}" in block
    assert "[Page 2]" not in block and "[Page 8]" not in block
    # 页码升序
    assert block.index("[Page 3]") < block.index("[Page 5]") < block.index("[Page 7]")


def test_context_block_budget_keeps_nearest_pages(data_root, pdf_project):
    pages = ["A" * 1000 for _ in range(10)]
    _seed_text(pdf_project.project_id, pdf_project.pdf_id, pages)
    # 预算只够 3 页：应保留选区页 5 及两侧最近的 4、6
    block = build_context_block(
        pdf_project.project_id,
        pdf_project.pdf_id,
        5,
        5,
        window_pages=2,
        max_chars=3000,
    )
    assert block is not None
    assert "[Page 4]" in block and "[Page 5]" in block and "[Page 6]" in block
    assert "[Page 3]" not in block and "[Page 7]" not in block


def test_context_block_selection_page_truncated_when_over_budget(data_root, pdf_project):
    pages = ["B" * 5000 for _ in range(3)]
    _seed_text(pdf_project.project_id, pdf_project.pdf_id, pages)
    block = build_context_block(
        pdf_project.project_id,
        pdf_project.pdf_id,
        2,
        2,
        window_pages=1,
        max_chars=1000,
    )
    assert block is not None
    assert "[Page 2]" in block
    # 截断后正文不超过预算（框架文案不计入预算）
    body = block.split("[Page 2]\n", 1)[1]
    assert len(body) == 1000


def test_context_block_none_when_not_ok(data_root, pdf_project):
    pages = ["C" * 100 for _ in range(3)]
    _seed_text(pdf_project.project_id, pdf_project.pdf_id, pages, status="unsupported")
    assert (
        build_context_block(
            pdf_project.project_id,
            pdf_project.pdf_id,
            2,
            2,
            window_pages=1,
            max_chars=1000,
        )
        is None
    )


def test_context_block_none_when_no_rows(data_root, pdf_project):
    assert (
        build_context_block(
            pdf_project.project_id,
            pdf_project.pdf_id,
            1,
            1,
            window_pages=2,
            max_chars=1000,
        )
        is None
    )


def test_context_block_multi_page_selection_anchor(data_root, pdf_project):
    pages = [f"page-{i} " + "y" * 30 for i in range(1, 11)]
    _seed_text(pdf_project.project_id, pdf_project.pdf_id, pages)
    block = build_context_block(
        pdf_project.project_id,
        pdf_project.pdf_id,
        4,
        6,
        window_pages=1,
        max_chars=100_000,
    )
    assert block is not None
    for i in (3, 4, 5, 6, 7):
        assert f"[Page {i}]" in block
    assert "[Page 2]" not in block and "[Page 8]" not in block
