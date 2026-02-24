from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_scheduler, get_store
from app.core.event_display import enrich_event_for_display
from app.core.plan_parser import build_exec_prompt
from app.models import (
    EventBatch,
    PlanBatchActionResult,
    PlanBatchConfirmInput,
    PlanBatchReviseInput,
    PlanConfirmInput,
    PlanReviseInput,
    Task,
    TaskCreateInput,
    TaskMode,
    TaskRetryInput,
    TaskStatus,
)
from app.store.json_store import JsonStore

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[Task])
def list_tasks(
    repo_id: str | None = Query(default=None),
    status: TaskStatus | None = Query(default=None),
    keyword: str | None = Query(default=None),
    store: JsonStore = Depends(get_store),
):
    return store.list_tasks(repo_id=repo_id, status=status, keyword=keyword)


@router.post("", response_model=Task)
def create_task(payload: TaskCreateInput, store: JsonStore = Depends(get_store)):
    repo = store.get_repo(payload.repo_id)
    if repo is None:
        raise HTTPException(status_code=400, detail=f"repo not found: {payload.repo_id}")
    if not repo.enabled:
        raise HTTPException(status_code=400, detail=f"repo disabled: {payload.repo_id}")
    task = store.create_task(payload.model_dump())
    return task


@router.get("/{task_id}", response_model=Task)
def get_task(task_id: str, store: JsonStore = Depends(get_store)):
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.get("/{task_id}/events", response_model=EventBatch)
def get_events(task_id: str, cursor: int = Query(default=0), store: JsonStore = Depends(get_store)):
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    events, next_cursor = store.read_events(task_id, cursor=cursor)
    decorated = [enrich_event_for_display(event) for event in events]
    return {"events": decorated, "next_cursor": next_cursor}


@router.post("/{task_id}/cancel", response_model=Task)
def cancel_task(task_id: str, store: JsonStore = Depends(get_store), scheduler=Depends(get_scheduler)):
    task = store.cancel_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    scheduler.request_cancel(task_id)
    return task


@router.post("/{task_id}/retry", response_model=Task)
def retry_task(task_id: str, payload: TaskRetryInput, store: JsonStore = Depends(get_store)):
    mode = payload.reset_mode
    task = store.reset_task_for_retry(task_id, reset_mode=mode)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.post("/{task_id}/done", response_model=Task)
def mark_done(task_id: str, store: JsonStore = Depends(get_store)):
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    if task.status != TaskStatus.REVIEW:
        raise HTTPException(status_code=400, detail=f"task status must be REVIEW, got {task.status}")
    patched = store.update_task(task_id, {"status": TaskStatus.DONE.value})
    assert patched is not None
    return patched


@router.post("/{task_id}/plan/confirm", response_model=Task)
def confirm_plan(task_id: str, payload: PlanConfirmInput, store: JsonStore = Depends(get_store)):
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    if task.status != TaskStatus.PLAN_REVIEW:
        raise HTTPException(status_code=400, detail=f"task status must be PLAN_REVIEW, got {task.status}")

    final_prompt = build_exec_prompt(task.prompt, task.plan_result, payload.answers)
    patched = store.update_task(
        task_id,
        {
            "mode": TaskMode.EXEC.value,
            "status": TaskStatus.READY.value,
            "prompt": final_prompt,
            "plan_answers": payload.answers,
            "error_code": "",
            "error_message": "",
            "cancel_requested": False,
        },
    )
    assert patched is not None
    return patched


@router.post("/{task_id}/plan/revise", response_model=Task)
def revise_plan(task_id: str, payload: PlanReviseInput, store: JsonStore = Depends(get_store)):
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    if task.status != TaskStatus.PLAN_REVIEW:
        raise HTTPException(status_code=400, detail=f"task status must be PLAN_REVIEW, got {task.status}")

    revised_prompt = f"{task.prompt}\n\n[用户反馈]\n{payload.feedback.strip()}"
    patched = store.update_task(
        task_id,
        {
            "mode": TaskMode.PLAN.value,
            "status": TaskStatus.TODO.value,
            "prompt": revised_prompt,
            "error_code": "",
            "error_message": "",
            "cancel_requested": False,
        },
    )
    assert patched is not None
    return patched


@router.post("/plan/batch/confirm", response_model=PlanBatchActionResult)
def batch_confirm_plan(payload: PlanBatchConfirmInput, store: JsonStore = Depends(get_store)):
    task_ids = store.normalize_task_ids(payload.task_ids)
    if len(task_ids) < 1 or len(task_ids) > 100:
        raise HTTPException(status_code=400, detail="task_ids count after dedupe must be between 1 and 100")

    updated, failed = store.batch_confirm_plan_tasks(task_ids)
    for task in updated:
        store.append_event(
            task.id,
            {
                "type": "plan_batch_confirm",
                "message": "Batch confirmed and moved to READY",
            },
        )
    return {
        "updated": updated,
        "failed": failed,
        "counts": {
            "requested": len(task_ids),
            "updated": len(updated),
            "failed": len(failed),
        },
    }


@router.post("/plan/batch/revise", response_model=PlanBatchActionResult)
def batch_revise_plan(payload: PlanBatchReviseInput, store: JsonStore = Depends(get_store)):
    task_ids = store.normalize_task_ids(payload.task_ids)
    feedback = payload.feedback.strip()
    if len(task_ids) < 1 or len(task_ids) > 100:
        raise HTTPException(status_code=400, detail="task_ids count after dedupe must be between 1 and 100")
    if not feedback:
        raise HTTPException(status_code=400, detail="feedback must not be empty")

    updated, failed = store.batch_revise_plan_tasks(task_ids, feedback)
    for task in updated:
        store.append_event(
            task.id,
            {
                "type": "plan_batch_revise",
                "message": "Batch revised and moved back to TODO",
            },
        )
    return {
        "updated": updated,
        "failed": failed,
        "counts": {
            "requested": len(task_ids),
            "updated": len(updated),
            "failed": len(failed),
        },
    }
