import type {
  BoardResponse,
  EventBatch,
  NotificationItem,
  PlanBatchActionResult,
  RepoConfig,
  Task,
  TaskMode,
  PermissionMode,
} from '../types'

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(text || `HTTP ${resp.status}`)
  }
  return (await resp.json()) as T
}

export const api = {
  listRepos: () => req<RepoConfig[]>('/api/repos'),
  rescanRepos: () => req<RepoConfig[]>('/api/repos/rescan', { method: 'POST' }),
  patchRepo: (repoId: string, payload: Partial<RepoConfig>) =>
    req<RepoConfig>(`/api/repos/${repoId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  getBoard: (repoId?: string) => req<BoardResponse>(`/api/board${repoId ? `?repo_id=${encodeURIComponent(repoId)}` : ''}`),
  listTasks: (repoId?: string) => req<Task[]>(`/api/tasks${repoId ? `?repo_id=${encodeURIComponent(repoId)}` : ''}`),
  createTask: (payload: {
    repo_id: string
    title: string
    prompt: string
    mode: TaskMode
    permission_mode: PermissionMode
    priority: number
  }) => req<Task>('/api/tasks', { method: 'POST', body: JSON.stringify(payload) }),
  getTask: (taskId: string) => req<Task>(`/api/tasks/${taskId}`),
  getTaskEvents: (taskId: string, cursor: number) =>
    req<EventBatch>(`/api/tasks/${taskId}/events?cursor=${cursor}`),
  cancelTask: (taskId: string) => req<Task>(`/api/tasks/${taskId}/cancel`, { method: 'POST' }),
  retryTask: (taskId: string) => req<Task>(`/api/tasks/${taskId}/retry`, { method: 'POST', body: '{}' }),
  markDone: (taskId: string) => req<Task>(`/api/tasks/${taskId}/done`, { method: 'POST' }),
  confirmPlan: (taskId: string, answers: Record<string, string>) =>
    req<Task>(`/api/tasks/${taskId}/plan/confirm`, {
      method: 'POST',
      body: JSON.stringify({ answers }),
    }),
  revisePlan: (taskId: string, feedback: string) =>
    req<Task>(`/api/tasks/${taskId}/plan/revise`, {
      method: 'POST',
      body: JSON.stringify({ feedback }),
    }),
  batchConfirmPlan: (taskIds: string[]) =>
    req<PlanBatchActionResult>('/api/tasks/plan/batch/confirm', {
      method: 'POST',
      body: JSON.stringify({ task_ids: taskIds }),
    }),
  batchRevisePlan: (taskIds: string[], feedback: string) =>
    req<PlanBatchActionResult>('/api/tasks/plan/batch/revise', {
      method: 'POST',
      body: JSON.stringify({ task_ids: taskIds, feedback }),
    }),
  listNotifications: () => req<NotificationItem[]>('/api/notifications'),
  markNotificationRead: (id: string) => req<NotificationItem>(`/api/notifications/${id}/read`, { method: 'POST' }),
}
