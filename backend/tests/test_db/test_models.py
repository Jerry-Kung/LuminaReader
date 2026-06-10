import sqlite3
import time

import pytest

from lumina.db.migrations import initialize_schema
from lumina.db.models import (
    MessageRow,
    SelectionRow,
    get_selection,
    get_selection_type,
    insert_message,
    insert_selection,
    list_messages,
)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    initialize_schema(connection)
    yield connection
    connection.close()


def _insert_message(conn, *, conversation_id: str, turn_index: int, role: str, content: str):
    insert_message(
        conn,
        MessageRow(
            id=f"msg_{turn_index}_{role}",
            conversation_id=conversation_id,
            turn_index=turn_index,
            role=role,
            content=content,
            user_question=content if role == "user" else None,
            model="gpt-4o" if role == "assistant" else None,
            prompt_tokens=1 if role == "assistant" else None,
            completion_tokens=1 if role == "assistant" else None,
            latency_ms=10 if role == "assistant" else None,
            created_at=int(time.time()),
        ),
    )


def test_list_messages_orders_user_before_assistant(conn):
    conv_id = "conv_test"
    _insert_message(
        conn, conversation_id=conv_id, turn_index=0, role="assistant", content="a"
    )
    _insert_message(
        conn, conversation_id=conv_id, turn_index=0, role="user", content="u"
    )
    rows = list_messages(conn, conv_id)
    assert [row.role for row in rows] == ["user", "assistant"]


def test_list_messages_orders_by_turn_index_first(conn):
    conv_id = "conv_test2"
    for turn_index, user, assistant in (
        (0, "u0", "a0"),
        (1, "u1", "a1"),
    ):
        _insert_message(
            conn, conversation_id=conv_id, turn_index=turn_index, role="user", content=user
        )
        _insert_message(
            conn,
            conversation_id=conv_id,
            turn_index=turn_index,
            role="assistant",
            content=assistant,
        )
    rows = list_messages(conn, conv_id)
    assert [row.content for row in rows] == ["u0", "a0", "u1", "a1"]


def test_insert_get_selection_image_path(conn) -> None:
    row = SelectionRow(
        id="sel_img",
        pdf_id="pdf_1",
        page=1,
        x=1.0,
        y=2.0,
        w=10.0,
        h=20.0,
        dpi=144.0,
        thumbnail_png=b"png",
        created_at=int(time.time()),
        type="image",
    )
    insert_selection(conn, row)
    loaded = get_selection(conn, "sel_img")
    assert loaded is not None
    assert loaded.type == "image"
    assert loaded.x == 1.0
    assert loaded.text is None


def test_insert_get_selection_text_path(conn) -> None:
    row = SelectionRow(
        id="sel_txt",
        pdf_id="pdf_1",
        page=5,
        x=None,
        y=None,
        w=None,
        h=None,
        dpi=None,
        thumbnail_png=None,
        created_at=int(time.time()),
        type="text",
        text="Hello",
        page_end=7,
        segments_json='[{"page":5,"text":"Hello","offset_start":0,"offset_end":5}]',
    )
    insert_selection(conn, row)
    loaded = get_selection(conn, "sel_txt")
    assert loaded is not None
    assert loaded.type == "text"
    assert loaded.text == "Hello"
    assert loaded.page_end == 7
    assert loaded.x is None


def test_get_selection_type_image(conn) -> None:
    insert_selection(
        conn,
        SelectionRow(
            id="sel_a",
            pdf_id="pdf_1",
            page=1,
            x=1.0,
            y=1.0,
            w=1.0,
            h=1.0,
            dpi=144.0,
            thumbnail_png=None,
            created_at=0,
            type="image",
        ),
    )
    assert get_selection_type(conn, "sel_a") == "image"


def test_get_selection_type_text(conn) -> None:
    insert_selection(
        conn,
        SelectionRow(
            id="sel_b",
            pdf_id="pdf_1",
            page=1,
            x=None,
            y=None,
            w=None,
            h=None,
            dpi=None,
            thumbnail_png=None,
            created_at=0,
            type="text",
            text="word",
            page_end=1,
            segments_json="[]",
        ),
    )
    assert get_selection_type(conn, "sel_b") == "text"


def test_get_selection_type_not_found(conn) -> None:
    assert get_selection_type(conn, "missing") is None
