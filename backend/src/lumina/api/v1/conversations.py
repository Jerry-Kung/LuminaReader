import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from lumina.db.engine import get_connection
from lumina.db.models import get_conversation, list_messages
from lumina.logging import get_logger, log_with_fields
from lumina.projects.manager import ProjectNotFoundError, lookup_project_by_conversation_id
from lumina.request_id import generate_request_id
from lumina.schemas.api import ConversationMessagesData, MessageItem, error_response, ok_response

router = APIRouter(prefix="/conversations", tags=["conversations"])
logger = get_logger("lumina.conversations")


def _to_message_item(row) -> MessageItem:
    base = MessageItem(
        message_id=row.id,
        turn_index=row.turn_index,
        role=row.role,
        content=row.content,
        created_at=row.created_at,
    )
    if row.role == "user":
        return base.model_copy(update={"user_question": row.user_question})
    return base.model_copy(
        update={
            "model": row.model,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "latency_ms": row.latency_ms,
        }
    )


@router.get("/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: str):
    request_id = generate_request_id()
    try:
        entry = lookup_project_by_conversation_id(conversation_id)
    except ProjectNotFoundError:
        log_with_fields(
            logger,
            logging.WARNING,
            "conversation messages not found",
            request_id=request_id,
            api_version="v1",
            http_status=404,
            error_code="SESSION_NOT_FOUND",
            conversation_id=conversation_id,
        )
        return JSONResponse(
            status_code=404,
            content=error_response(
                code="SESSION_NOT_FOUND",
                message="Conversation not found.",
                request_id=request_id,
            ),
        )

    conn = get_connection(entry.id)
    conv = get_conversation(conn, conversation_id)
    if conv is None or conv.status == "cleared":
        log_with_fields(
            logger,
            logging.WARNING,
            "conversation messages cleared or missing",
            request_id=request_id,
            api_version="v1",
            http_status=404,
            error_code="SESSION_NOT_FOUND",
            conversation_id=conversation_id,
            project_id=entry.id,
            pdf_id=conv.pdf_id if conv else "",
        )
        return JSONResponse(
            status_code=404,
            content=error_response(
                code="SESSION_NOT_FOUND",
                message="Conversation not found.",
                request_id=request_id,
            ),
        )

    messages = [_to_message_item(m) for m in list_messages(conn, conversation_id)]
    data = ConversationMessagesData(
        conversation_id=conv.id,
        task_type=conv.task_type,
        extracted_text=conv.extracted_text,
        messages=messages,
    )
    log_with_fields(
        logger,
        logging.INFO,
        "conversation messages loaded",
        request_id=request_id,
        api_version="v1",
        http_status=200,
        conversation_id=conversation_id,
        project_id=entry.id,
        pdf_id=conv.pdf_id,
    )
    return ok_response(data)
