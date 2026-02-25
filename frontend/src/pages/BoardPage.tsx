import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import TaskCard from '../components/TaskCard'
import TaskComposer from '../components/TaskComposer'
import type { BoardResponse, NotificationItem, RepoConfig } from '../types'

const COLUMN_MAP: Array<{ key: string; title: string }> = [
  { key: 'TODO', title: '待开发' },
  { key: 'RUNNING', title: '开发中' },
  { key: 'REVIEW', title: '待 Review' },
  { key: 'DONE', title: '已完成' },
  { key: 'FAILED', title: '失败' },
  { key: 'CANCELLED', title: '已取消' },
]

export default function BoardPage({ onOpenTask }: { onOpenTask: (taskId: string) => void }) {
  const [repos, setRepos] = useState<RepoConfig[]>([])
  const [selectedRepoId, setSelectedRepoId] = useState('')
  const [board, setBoard] = useState<BoardResponse>({
    columns: { TODO: [], RUNNING: [], REVIEW: [], DONE: [], FAILED: [], CANCELLED: [] },
    counts: { TODO: 0, RUNNING: 0, REVIEW: 0, DONE: 0, FAILED: 0, CANCELLED: 0 },
  })
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [error, setError] = useState('')
  const [selectedPlanTaskIds, setSelectedPlanTaskIds] = useState<Set<string>>(new Set())
  const [batchFeedback, setBatchFeedback] = useState('')
  const [batchResultMessage, setBatchResultMessage] = useState('')
  const [batchErrorMessage, setBatchErrorMessage] = useState('')
  const [batchSubmitting, setBatchSubmitting] = useState(false)

  function summarizeBatchFailures(
    failed: Array<{ task_id: string; error_code: string; error_message: string }>,
  ) {
    if (failed.length === 0) return ''
    const sample = failed
      .slice(0, 3)
      .map((item) => `${item.task_id}: ${item.error_code}`)
      .join('；')
    return `失败 ${failed.length} 项${sample ? `（示例：${sample}）` : ''}`
  }

  async function refreshAll() {
    try {
      const [repoResp, notifResp] = await Promise.all([api.listRepos(), api.listNotifications()])
      setRepos(repoResp)
      setNotifications(notifResp)
      const chosen = selectedRepoId || repoResp.find((r) => r.enabled)?.id || ''
      setSelectedRepoId(chosen)
      const boardResp = await api.getBoard(chosen || undefined)
      setBoard(boardResp)
      const alivePlanReviewIds = new Set(
        Object.values(boardResp.columns)
          .flat()
          .filter((task) => task.status === 'PLAN_REVIEW')
          .map((task) => task.id),
      )
      setSelectedPlanTaskIds((prev) => {
        const next = new Set<string>()
        for (const taskId of prev) {
          if (alivePlanReviewIds.has(taskId)) next.add(taskId)
        }
        return next
      })
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    }
  }

  useEffect(() => {
    void refreshAll()
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refreshAll()
    }, 3000)
    return () => window.clearInterval(timer)
  }, [selectedRepoId])

  const unreadCount = useMemo(() => notifications.filter((n) => !n.read).length, [notifications])
  const totalTaskCount = useMemo(
    () => Object.values(board.counts).reduce((sum, count) => sum + count, 0),
    [board.counts],
  )
  const selectedPlanCount = selectedPlanTaskIds.size

  async function createTask(payload: {
    repo_id: string
    title: string
    prompt: string
    mode: 'PLAN' | 'EXEC'
    permission_mode: 'BYPASS' | 'DEFAULT'
    priority: number
  }) {
    await api.createTask(payload)
    await refreshAll()
  }

  async function onRescanRepos() {
    await api.rescanRepos()
    await refreshAll()
  }

  function togglePlanTask(taskId: string, checked: boolean) {
    setSelectedPlanTaskIds((prev) => {
      const next = new Set(prev)
      if (checked) next.add(taskId)
      else next.delete(taskId)
      return next
    })
  }

  function clearPlanSelection() {
    setSelectedPlanTaskIds(new Set())
  }

  async function onBatchConfirmPlan() {
    if (selectedPlanCount === 0 || batchSubmitting) return
    setBatchSubmitting(true)
    setBatchResultMessage('')
    setBatchErrorMessage('')
    try {
      const taskIds = Array.from(selectedPlanTaskIds)
      const result = await api.batchConfirmPlan(taskIds)
      setBatchResultMessage(
        `批量确认完成：请求 ${result.counts.requested}，成功 ${result.counts.updated}，失败 ${result.counts.failed}`,
      )
      if (result.counts.failed > 0) {
        setBatchErrorMessage(summarizeBatchFailures(result.failed))
      }
      await refreshAll()
    } catch (e) {
      setBatchErrorMessage(e instanceof Error ? e.message : '批量确认失败')
    } finally {
      setBatchSubmitting(false)
    }
  }

  async function onBatchRevisePlan() {
    if (selectedPlanCount === 0 || batchSubmitting) return
    const feedback = batchFeedback.trim()
    if (!feedback) {
      setBatchErrorMessage('批量退回需要填写反馈')
      return
    }
    setBatchSubmitting(true)
    setBatchResultMessage('')
    setBatchErrorMessage('')
    try {
      const taskIds = Array.from(selectedPlanTaskIds)
      const result = await api.batchRevisePlan(taskIds, feedback)
      setBatchResultMessage(
        `批量退回完成：请求 ${result.counts.requested}，成功 ${result.counts.updated}，失败 ${result.counts.failed}`,
      )
      if (result.counts.failed > 0) {
        setBatchErrorMessage(summarizeBatchFailures(result.failed))
      }
      if (result.counts.updated > 0) {
        setBatchFeedback('')
      }
      await refreshAll()
    } catch (e) {
      setBatchErrorMessage(e instanceof Error ? e.message : '批量退回失败')
    } finally {
      setBatchSubmitting(false)
    }
  }

  return (
    <div className="page">
      <header className="topbar">
        <div className="topbar-left">
          <button className="topbar-nav" type="button" aria-label="返回上一页">
            &lt;
          </button>
          <div className="brand-logo">{'</>'}</div>
          <div>
            <h1>Claude Code 任务管理中心</h1>
            <p>共 {totalTaskCount} 个任务</p>
          </div>
        </div>
        <div className="topbar-icons">
          <button className="icon-btn icon-btn-quiet" type="button" aria-label="切换主题">
            ◐
          </button>
          <button className="icon-btn icon-btn-quiet" type="button" aria-label="切换语言">
            A EN
          </button>
        </div>
      </header>

      <section className="toolbar-row">
        <div className="toolbar-left">
          <select value={selectedRepoId} className="input" onChange={(e) => setSelectedRepoId(e.target.value)}>
            <option value="">全部仓库</option>
            {repos.map((repo) => (
              <option key={repo.id} value={repo.id}>
                {repo.name} {repo.enabled ? '' : '(已禁用)'}
              </option>
            ))}
          </select>
        </div>
        <div className="toolbar-actions">
          <button className="button" onClick={onRescanRepos}>
            扫描仓库
          </button>
          <button className="button" onClick={() => void refreshAll()}>
            刷新
          </button>
          <span className="notif">通知 {unreadCount}</span>
        </div>
      </section>

      <TaskComposer selectedRepoId={selectedRepoId} onCreate={createTask} />

      <section className="batch-bar">
        <div className="batch-bar-actions">
          <span className="batch-count">已选 {selectedPlanCount} 项 Plan 审查任务</span>
          <button className="button" onClick={clearPlanSelection} disabled={selectedPlanCount === 0 || batchSubmitting}>
            清空选择
          </button>
          <button
            className="button button-primary"
            onClick={onBatchConfirmPlan}
            disabled={selectedPlanCount === 0 || batchSubmitting}
          >
            批量确认并执行
          </button>
        </div>
        <div className="batch-bar-revise">
          <input
            className="input"
            value={batchFeedback}
            onChange={(event) => setBatchFeedback(event.target.value)}
            placeholder="批量退回反馈（将追加到每个任务）"
          />
          <button
            className="button"
            onClick={onBatchRevisePlan}
            disabled={selectedPlanCount === 0 || batchSubmitting || !batchFeedback.trim()}
          >
            批量退回
          </button>
        </div>
        {batchResultMessage && <div className="batch-message">{batchResultMessage}</div>}
        {batchErrorMessage && <div className="batch-message batch-message-error">{batchErrorMessage}</div>}
      </section>

      {error && <div className="alert">{error}</div>}

      <section className="board-grid">
        {COLUMN_MAP.map((column) => {
          const tasks = board.columns[column.key] ?? []
          const columnClassName = `board-col board-col-${column.key.toLowerCase()}`
          return (
            <div className={columnClassName} key={column.key}>
              <div className="board-col-title">
                <span>{column.title}</span>
                <span className="count">{board.counts[column.key] ?? 0}</span>
              </div>
              <div className="board-col-body">
                {tasks.length === 0 ? (
                  <div className="board-col-empty">无任务</div>
                ) : (
                  tasks.map((task) => (
                    <TaskCard
                      key={task.id}
                      task={task}
                      columnKey={column.key}
                      onOpen={(task) => onOpenTask(task.id)}
                      selectable={task.status === 'PLAN_REVIEW'}
                      selected={selectedPlanTaskIds.has(task.id)}
                      onToggleSelect={togglePlanTask}
                    />
                  ))
                )}
              </div>
            </div>
          )
        })}
      </section>

    </div>
  )
}
