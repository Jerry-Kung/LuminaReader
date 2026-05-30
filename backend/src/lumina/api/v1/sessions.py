from fastapi import APIRouter, Depends, Response, status

from lumina.sessions import SessionStore, get_session_store

router = APIRouter()


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> Response:
    deleted = await store.delete(session_id)
    if not deleted:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
