import { useMemo, useState, type KeyboardEvent } from 'react'
import type { PermissionMode, TaskMode } from '../types'

interface Props {
  selectedRepoId: string
  onCreate: (payload: {
    repo_id: string
    title: string
    prompt: string
    mode: TaskMode
    permission_mode: PermissionMode
    priority: number
  }) => Promise<void>
}

function deriveTitleFromPrompt(prompt: string) {
  const firstLine = prompt
    .split('\n')
    .map((line) => line.trim())
    .find((line) => line.length > 0)
  if (!firstLine) return '新任务'
  return firstLine.slice(0, 36)
}

export default function TaskComposer({ selectedRepoId, onCreate }: Props) {
  const [prompt, setPrompt] = useState('')
  const [mode, setMode] = useState<TaskMode>('PLAN')
  const permissionMode: PermissionMode = 'BYPASS'
  const priority = 0
  const [submitting, setSubmitting] = useState(false)

  const disabled = useMemo(() => !prompt.trim() || !selectedRepoId, [prompt, selectedRepoId])

  async function submit() {
    if (disabled || submitting) return
    setSubmitting(true)
    try {
      const cleanPrompt = prompt.trim()
      await onCreate({
        repo_id: selectedRepoId,
        title: deriveTitleFromPrompt(cleanPrompt),
        prompt: cleanPrompt,
        mode,
        permission_mode: permissionMode,
        priority,
      })
      setPrompt('')
      setMode('PLAN')
    } finally {
      setSubmitting(false)
    }
  }

  function onPromptKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault()
      void submit()
    }
  }

  return (
    <section className="composer">
      <div className="composer-main-row">
        <textarea
          className="composer-prompt"
          placeholder="添加新任务... (Cmd/Ctrl+Enter 提交)"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={onPromptKeyDown}
        />
        <button className="icon-btn composer-mic" type="button" aria-label="语音输入">
          语音
        </button>
        <button className="button button-primary composer-add" onClick={submit} disabled={disabled || submitting}>
          {submitting ? '提交中...' : '添加'}
        </button>
      </div>

      <div className="composer-chain-row">
        <label className="muted">前序任务:</label>
        <select className="input composer-chain-select" defaultValue="none">
          <option value="none">无（立即开始）</option>
        </select>
      </div>

      <div className="composer-foot-row">
        <label className="composer-plan-check">
          <span className="plan-check-icon">◎</span>
          <input type="checkbox" checked={mode === 'PLAN'} onChange={(e) => setMode(e.target.checked ? 'PLAN' : 'EXEC')} />
          <span>Plan 模式</span>
        </label>
        <span className="muted composer-hint">Plan 先行，确认后执行 | Cmd/Ctrl+Enter 提交</span>
      </div>
    </section>
  )
}
