from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_store
from app.models import BoardResponse
from app.store.json_store import JsonStore

router = APIRouter(prefix="/api", tags=["board"])


@router.get("/board", response_model=BoardResponse)
def get_board(repo_id: str | None = Query(default=None), store: JsonStore = Depends(get_store)):
    columns, counts = store.board(repo_id=repo_id)
    return {"columns": columns, "counts": counts}
