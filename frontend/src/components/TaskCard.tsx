import type { Task } from '../types'

interface Props {
  task: Task
  columnKey: string
  onOpen: (task: Task) => void
  selected?: boolean
  selectable?: boolean
  onToggleSelect?: (taskId: string, checked: boolean) => void
}

function formatRelativeTime(ts: string) {
  const diff = Date.now() - new Date(ts).getTime()
  const minute = 60 * 1000
  const hour = 60 * minute
  const day = 24 * hour

  if (Number.isNaN(diff) || diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  return `${Math.floor(diff / day)} 天前`
}

export default function TaskCard({
  task,
  columnKey,
  onOpen,
  selected = false,
  selectable = false,
  onToggleSelect,
}: Props) {
  const cardClassName = `task-card task-card-${columnKey.toLowerCase()}`
  const idText = task.id
  const timePrefix = task.status === 'FAILED' ? '失败' : task.status === 'DONE' ? '完成' : '更新'

  return (
    <article className={cardClassName} onClick={() => onOpen(task)}>
      <div className="task-card-top">
        <div className="task-card-id-group">
          {selectable && (
            <input
              className="task-plan-checkbox"
              type="checkbox"
              checked={selected}
              onClick={(event) => event.stopPropagation()}
              onChange={(event) => onToggleSelect?.(task.id, event.target.checked)}
              aria-label={`选择任务 ${task.id}`}
            />
          )}
          <span className="task-id">{idText}</span>
        </div>
        <span className="task-chevron">v</span>
      </div>
      {task.mode === 'PLAN' && <span className="status-tag status-plan">◎ Plan</span>}
      <h4>{task.title}</h4>
      <p>{task.prompt.slice(0, 120)}</p>
      <div className="task-meta">
        <span>{timePrefix}: {formatRelativeTime(task.updated_at)}</span>
      </div>
      {task.error_message && <div className="task-error">{task.error_message.slice(0, 80)}</div>}
    </article>
  )
}
