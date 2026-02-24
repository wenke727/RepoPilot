from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_store
from app.models import RepoConfig, RepoPatchInput
from app.store.json_store import JsonStore

router = APIRouter(prefix="/api/repos", tags=["repos"])


@router.get("", response_model=list[RepoConfig])
def list_repos(store: JsonStore = Depends(get_store)):
    return store.list_repos()


@router.post("/rescan", response_model=list[RepoConfig])
def rescan_repos(store: JsonStore = Depends(get_store)):
    return store.rescan_repos()


@router.patch("/{repo_id}", response_model=RepoConfig)
def patch_repo(repo_id: str, payload: RepoPatchInput, store: JsonStore = Depends(get_store)):
    patched = store.patch_repo(repo_id, payload.model_dump())
    if not patched:
        raise HTTPException(status_code=404, detail="repo not found")
    return patched
