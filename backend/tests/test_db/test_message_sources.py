"""V1.2.4 messages.sources_json 列读写（MAY 档：可空，concept-recall 专用）。"""

import sqlite3

import pytest

from lumina.db.migrations import initialize_schema
from lumina.db.models import (
    ConversationRow,
    MessageRow,
    get_first_assistant_message,
    insert_conversation,
    insert_message,
    list_messages,
    update_assistant_message_at_turn,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", isolation_level=None)
    initialize_schema(c)
    c.execute(
        "INSERT INTO project_meta (id, name, created_at, schema_version) VALUES ('proj_x', 'x', 0, 8)"
    )
    insert_conversation(
        c,
        ConversationRow(
            id="conv_1", pdf_id="pdf_1", selection_id="sel_1",
            task_type="concept-recall", extracted_text="",
            created_at=0, last_used_at=0, status="active",
        ),
    )
    yield c
    c.close()


def _msg(**kw) -> MessageRow:
    base = dict(
        id="msg_a", conversation_id="conv_1", turn_index=0, role="assistant",
        content="answer", user_question=None, model="m",
        prompt_tokens=1, completion_tokens=2, latency_ms=3, created_at=0,
    )
    base.update(kw)
    return MessageRow(**base)


def test_insert_and_read_sources_json(conn):
    insert_message(conn, _msg(sources_json='[{"kind":"concept","term":"t","page":5}]'))
    rows = list_messages(conn, "conv_1")
    assert rows[0].sources_json == '[{"kind":"concept","term":"t","page":5}]'
    first = get_first_assistant_message(conn, "conv_1")
    assert first is not None and first.sources_json is not None


def test_sources_json_defaults_null(conn):
    insert_message(conn, _msg(id="msg_b"))  # 不传 sources_json
    rows = list_messages(conn, "conv_1")
    assert rows[0].sources_json is None


def test_update_assistant_message_writes_sources(conn):
    insert_message(conn, _msg(id="msg_c", content="", sources_json=None))
    update_assistant_message_at_turn(
        conn, "conv_1", 0,
        content="final", model="m2",
        prompt_tokens=None, completion_tokens=None, latency_ms=10,
        sources_json='[{"kind":"text","page":9,"snippet":"s"}]',
    )
    rows = list_messages(conn, "conv_1")
    assert rows[0].content == "final"
    assert rows[0].sources_json == '[{"kind":"text","page":9,"snippet":"s"}]'
