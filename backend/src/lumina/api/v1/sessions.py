from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from lumina.schemas.api import error_response
from lumina.request_id import generate_request_id
from lumina.sessions import DbWriteError, SessionStore, get_session_store

router = APIRouter()


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> Response:
    try:
        deleted = await store.delete(session_id)
    except DbWriteError:
        request_id = generate_request_id()
        return JSONResponse(
            status_code=500,
            content=error_response(
                code="INTERNAL_ERROR",
                message="An internal server error occurred.",
                request_id=request_id,
            ),
        )
    if not deleted:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
