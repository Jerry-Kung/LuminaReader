import sqlite3
import time

import pytest

from lumina.db.migrations import initialize_schema
from lumina.db.models import MessageRow, insert_message, list_messages


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
