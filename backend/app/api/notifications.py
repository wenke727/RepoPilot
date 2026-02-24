from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_store
from app.models import Notification
from app.store.json_store import JsonStore

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[Notification])
def list_notifications(store: JsonStore = Depends(get_store)):
    return store.list_notifications()


@router.post("/{notification_id}/read", response_model=Notification)
def mark_read(notification_id: str, store: JsonStore = Depends(get_store)):
    notif = store.mark_notification_read(notification_id)
    if notif is None:
        raise HTTPException(status_code=404, detail="notification not found")
    return notif
