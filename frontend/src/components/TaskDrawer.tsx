import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import PlanChoiceCard from './PlanChoiceCard'
import {
  deriveInitialAnswers,
  isPlanAnswersComplete,
  normalizePlanResult,
} from '../plan/selection'
import type { Task, TaskEvent, TaskEventDisplay, TaskEventDisplayGroup } from '../types'
import type { NormalizedPlanResult } from '../plan/selection'

interface Props {
  task: Task | null
  onClose: () => void
  onChanged: () => Promise<void>
}

interface LogEntry {
  key: string
  group: TaskEventDisplayGroup
  label: string
  time: string
  seq: string
  message: string
  raw: string
  mergeKey: string
}

interface LogRawEntry {
  seq: string
  raw: string
}

interface LogBlock {
  key: string
  group: TaskEventDisplayGroup
  label: string
  mergeKey: string
  count: number
  seqStart: string
  seqEnd: string
  time: string
  message: string
  rawEntries: LogRawEntry[]
}

const LOG_EVENT_LIMIT = 2000
const LOG_BLOCK_LIMIT = 300
const FOLLOW_BOTTOM_THRESHOLD = 24

const GROUP_LABELS: Record<TaskEventDisplayGroup, string> = {
  command: '命令',
  output: '输出',
  result: '结果',
  timeout: '超时',
  artifact: '产物',
  protocol: '协议',
}

const DEFAULT_GROUP_FILTERS: Record<TaskEventDisplayGroup, boolean> = {
  command: true,
  output: true,
  result: true,
  timeout: true,
  artifact: true,
  protocol: false,
}

const GROUP_FILTER_OPTIONS: Array<{ group: TaskEventDisplayGroup; label: string }> = [
  { group: 'command', label: '命令' },
  { group: 'output', label: '输出' },
  { group: 'result', label: '结果' },
  { group: 'timeout', label: '超时' },
  { group: 'artifact', label: '产物' },
  { group: 'protocol', label: '协议' },
]

function formatEventTime(ts: string): string {
  if (!ts) return '--:--:--'
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

function pickString(source: TaskEvent, key: string): string {
  const value = source[key]
  return typeof value === 'string' ? value : ''
}

function asDisplayGroup(value: string): TaskEventDisplayGroup {
  switch (value) {
    case 'command':
    case 'output':
    case 'result':
    case 'timeout':
    case 'artifact':
    case 'protocol':
      return value
    default:
      return 'protocol'
  }
}

function truncatePreview(text: string): string {
  return text
}

function toRawEventJson(event: TaskEvent): string {
  const view: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(event)) {
    if (key === 'seq' || key === 'display') continue
    view[key] = value
  }
  return JSON.stringify(view, null, 2)
}

function extractAssistantText(payload: Record<string, unknown>): string[] {
  const message = payload.message
  if (!message || typeof message !== 'object' || Array.isArray(message)) return []
  const content = (message as Record<string, unknown>).content
  if (!Array.isArray(content)) return []

  const chunks: string[] = []
  for (const item of content) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue
    const text = (item as Record<string, unknown>).text
    if (typeof text === 'string' && text.trim()) chunks.push(text.trim())
  }
  return chunks
}

function extractAssistantToolNames(payload: Record<string, unknown>): string[] {
  const message = payload.message
  if (!message || typeof message !== 'object' || Array.isArray(message)) return []
  const content = (message as Record<string, unknown>).content
  if (!Array.isArray(content)) return []

  const names: string[] = []
  for (const item of content) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue
    const view = item as Record<string, unknown>
    if (view.type !== 'tool_use') continue
    if (typeof view.name === 'string' && view.name.trim()) names.push(view.name.trim())
  }
  return names
}

function containsUserToolResult(payload: Record<string, unknown>): boolean {
  const message = payload.message
  if (!message || typeof message !== 'object' || Array.isArray(message)) return false
  const content = (message as Record<string, unknown>).content
  if (!Array.isArray(content)) return false

  for (const item of content) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue
    if ((item as Record<string, unknown>).type === 'tool_result') return true
  }
  return false
}

function describeStreamProtocol(payload: Record<string, unknown>): string {
  const streamType = typeof payload.type === 'string' ? payload.type : ''
  const streamSubtype = typeof payload.subtype === 'string' ? payload.subtype : ''

  if (streamType === 'assistant') {
    const toolNames = extractAssistantToolNames(payload)
    if (toolNames.length > 0) return `助手调用工具: ${toolNames.join(', ')}`
    return '助手协议消息'
  }

  if (streamType === 'user') {
    if (containsUserToolResult(payload)) return '工具返回结果'
    return '用户协议消息'
  }

  if (streamType === 'system') return `系统事件: ${streamSubtype || 'event'}`
  if (streamType === 'result') return `结果事件: ${streamSubtype || 'event'}`
  if (streamType) return `协议事件: ${streamType}`
  return '协议事件'
}

function buildFallbackStreamDisplay(event: TaskEvent): TaskEventDisplay {
  const line = pickString(event, 'line')
  const raw = line || toRawEventJson(event)
  if (!line) {
    return {
      group: 'protocol',
      label: GROUP_LABELS.protocol,
      text: '(空输出)',
      merge_key: 'protocol:empty',
      raw,
    }
  }

  try {
    const payload = JSON.parse(line) as Record<string, unknown>
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      return {
        group: 'protocol',
        label: GROUP_LABELS.protocol,
        text: truncatePreview(line),
        merge_key: 'protocol:non_object',
        raw,
      }
    }

    const streamType = typeof payload.type === 'string' ? payload.type : ''
    const streamSubtype = typeof payload.subtype === 'string' ? payload.subtype : ''
    const mergeSuffix = streamSubtype || streamType || 'unknown'

    if (streamType === 'assistant') {
      const texts = extractAssistantText(payload)
      if (texts.length > 0) {
        return {
          group: 'output',
          label: GROUP_LABELS.output,
          text: truncatePreview(texts.join('\n')),
          merge_key: `output:${mergeSuffix}`,
          raw,
        }
      }
      return {
        group: 'protocol',
        label: GROUP_LABELS.protocol,
        text: truncatePreview(describeStreamProtocol(payload)),
        merge_key: `protocol:${mergeSuffix}`,
        raw,
      }
    }

    if (streamType === 'result' && streamSubtype === 'success') {
      const result = typeof payload.result === 'string' && payload.result.trim() ? payload.result : '执行完成'
      return {
        group: 'result',
        label: GROUP_LABELS.result,
        text: truncatePreview(result),
        merge_key: 'result:success',
        raw,
      }
    }

    return {
      group: 'protocol',
      label: GROUP_LABELS.protocol,
      text: truncatePreview(describeStreamProtocol(payload)),
      merge_key: `protocol:${mergeSuffix}`,
      raw,
    }
  } catch {
    return {
      group: 'protocol',
      label: GROUP_LABELS.protocol,
      text: truncatePreview(line),
      merge_key: 'protocol:unparsed',
      raw,
    }
  }
}

function buildFallbackDisplay(event: TaskEvent): TaskEventDisplay {
  const type = pickString(event, 'type')
  const raw = toRawEventJson(event)

  if (type === 'command') {
    return {
      group: 'command',
      label: GROUP_LABELS.command,
      text: truncatePreview(pickString(event, 'cmd') || '(无命令内容)'),
      merge_key: 'command:command',
      raw,
    }
  }

  if (type === 'stream') return buildFallbackStreamDisplay(event)

  if (type === 'assistant_text') {
    return {
      group: 'result',
      label: GROUP_LABELS.result,
      text: truncatePreview(pickString(event, 'text') || '(无文本结果)'),
      merge_key: 'result:assistant_text',
      raw,
    }
  }

  if (type === 'timeout') {
    return {
      group: 'timeout',
      label: GROUP_LABELS.timeout,
      text: truncatePreview(pickString(event, 'message') || '任务超时'),
      merge_key: 'timeout:timeout',
      raw,
    }
  }

  if (type === 'artifact') {
    return {
      group: 'artifact',
      label: GROUP_LABELS.artifact,
      text: truncatePreview(pickString(event, 'path') || '(无产物路径)'),
      merge_key: 'artifact:artifact',
      raw,
    }
  }

  const fallback = pickString(event, 'message') || `事件类型: ${type || 'unknown'}`
  return {
    group: 'protocol',
    label: GROUP_LABELS.protocol,
    text: truncatePreview(fallback),
    merge_key: `protocol:${type || 'other'}`,
    raw,
  }
}

function toDisplay(event: TaskEvent): TaskEventDisplay {
  const candidate = event.display
  if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
    return buildFallbackDisplay(event)
  }

  const view = candidate as Record<string, unknown>
  const group = asDisplayGroup(typeof view.group === 'string' ? view.group : '')
  const label = typeof view.label === 'string' && view.label.trim() ? view.label : GROUP_LABELS[group]
  const text = typeof view.text === 'string' && view.text.trim() ? truncatePreview(view.text.trim()) : '(空输出)'
  const mergeKey =
    typeof view.merge_key === 'string' && view.merge_key.trim() ? view.merge_key : `${group}:${group}`
  const raw = typeof view.raw === 'string' && view.raw ? view.raw : toRawEventJson(event)

  return { group, label, text, merge_key: mergeKey, raw }
}

function toLogEntry(event: TaskEvent, index: number): LogEntry {
  const seqRaw = event.seq
  const seq = typeof seqRaw === 'number' || typeof seqRaw === 'string' ? String(seqRaw) : '-'
  const time = formatEventTime(typeof event.ts === 'string' ? event.ts : '')
  const display = toDisplay(event)
  return {
    key: `${seq}-${index}`,
    group: display.group,
    label: display.label,
    time,
    seq,
    message: display.text,
    raw: display.raw,
    mergeKey: display.merge_key,
  }
}

function appendMergedMessage(prev: string, next: string): string {
  if (!next) return prev
  if (!prev) return next
  return `${prev}\n${next}`
}

function shouldMergeEntry(prev: LogBlock | undefined, entry: LogEntry): boolean {
  if (!prev) return false
  if (entry.group === 'output' || entry.group === 'result') return false
  return prev.mergeKey === entry.mergeKey
}

function mergeLogEntries(entries: LogEntry[]): LogBlock[] {
  const blocks: LogBlock[] = []
  for (const entry of entries) {
    const prev = blocks[blocks.length - 1]
    if (shouldMergeEntry(prev, entry)) {
      prev.count += 1
      prev.seqEnd = entry.seq
      prev.time = entry.time
      prev.message = appendMergedMessage(prev.message, entry.message)
      prev.rawEntries.push({ seq: entry.seq, raw: entry.raw })
      continue
    }
    blocks.push({
      key: `${entry.mergeKey}:${entry.seq}`,
      group: entry.group,
      label: entry.label,
      mergeKey: entry.mergeKey,
      count: 1,
      seqStart: entry.seq,
      seqEnd: entry.seq,
      time: entry.time,
      message: entry.message,
      rawEntries: [{ seq: entry.seq, raw: entry.raw }],
    })
  }
  return blocks.slice(-LOG_BLOCK_LIMIT)
}

function formatRawEntries(entries: LogRawEntry[]): string {
  return entries
    .map((entry, index) => `${index > 0 ? '\n\n-----\n' : ''}#${entry.seq}\n${entry.raw}`)
    .join('')
}

function renderPlanDetailBlocks(plan: NormalizedPlanResult): JSX.Element | null {
  const hasContent = Boolean(
    plan.summary ||
      plan.estimatedTime ||
      plan.validation ||
      plan.rollback ||
      plan.recommendedPrompt ||
      plan.steps.length > 0 ||
      plan.risks.length > 0 ||
      plan.affectedFiles.length > 0 ||
      plan.newDependencies.length > 0,
  )
  if (!hasContent) return null

  return (
    <div className="plan-details-section">
      {plan.summary && (
        <div className="plan-detail-block">
          <strong>摘要:</strong>
          <p className="plan-meta-text">{plan.summary}</p>
        </div>
      )}
      {plan.steps.length > 0 && (
        <div className="plan-detail-block">
          <strong>实施步骤:</strong>
          <ol className="plan-steps-list">
            {plan.steps.map((step, i) => (
              <li key={`step-${i}`}>{step}</li>
            ))}
          </ol>
        </div>
      )}
      {plan.risks.length > 0 && (
        <div className="plan-detail-block">
          <strong>风险评估:</strong>
          <ul className="plan-risks-list">
            {plan.risks.map((risk, i) => (
              <li key={`risk-${i}`} className="plan-risk-item">{risk}</li>
            ))}
          </ul>
        </div>
      )}
      {plan.affectedFiles.length > 0 && (
        <div className="plan-detail-block">
          <strong>涉及文件:</strong>
          <div className="plan-files-list">
            {plan.affectedFiles.map((file, i) => (
              <code key={`file-${i}`} className="plan-file-item">{file}</code>
            ))}
          </div>
        </div>
      )}
      {plan.newDependencies.length > 0 && (
        <div className="plan-detail-block">
          <strong>新增依赖:</strong>
          <div className="plan-deps-list">
            {plan.newDependencies.map((dep, i) => (
              <span key={`dep-${i}`} className="plan-dep-item">{dep}</span>
            ))}
          </div>
        </div>
      )}
      {plan.estimatedTime && (
        <div className="plan-detail-block">
          <strong>预计执行时间:</strong>
          <span className="plan-meta-value">{plan.estimatedTime}</span>
        </div>
      )}
      {plan.validation && (
        <div className="plan-detail-block">
          <strong>验证方法:</strong>
          <p className="plan-meta-text">{plan.validation}</p>
        </div>
      )}
      {plan.rollback && (
        <div className="plan-detail-block">
          <strong>回滚方式:</strong>
          <p className="plan-meta-text">{plan.rollback}</p>
        </div>
      )}
      {plan.recommendedPrompt && (
        <div className="plan-detail-block">
          <strong>建议执行 Prompt:</strong>
          <pre className="chat-bubble-text">{plan.recommendedPrompt}</pre>
        </div>
      )}
    </div>
  )
}

export default function TaskDrawer({ task, onClose, onChanged }: Props) {
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [currentTask, setCurrentTask] = useState<Task | null>(task)
  const [feedback, setFeedback] = useState('')
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [groupFilters, setGroupFilters] = useState<Record<TaskEventDisplayGroup, boolean>>(DEFAULT_GROUP_FILTERS)
  const [followLogs, setFollowLogs] = useState(true)
  const [expandedRawBlocks, setExpandedRawBlocks] = useState<Set<string>>(new Set())
  const logBoxRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    setCurrentTask(task)
    setEvents([])
    setFeedback('')
    setAnswers({})
    setGroupFilters(DEFAULT_GROUP_FILTERS)
    setFollowLogs(true)
    setExpandedRawBlocks(new Set())
  }, [task?.id])

  useEffect(() => {
    if (!currentTask) return
    const taskId = currentTask.id
    let active = true
    let localCursor = 0
    let timer: number | undefined

    async function poll() {
      if (!active) return
      try {
        const [taskResp, batch] = await Promise.all([
          api.getTask(taskId),
          api.getTaskEvents(taskId, localCursor),
        ])
        if (!active) return
        setCurrentTask(taskResp)
        if (batch.events.length > 0) {
          setEvents((prev) => {
            const merged = [...prev, ...batch.events]
            if (merged.length <= LOG_EVENT_LIMIT) return merged
            return merged.slice(-LOG_EVENT_LIMIT)
          })
          localCursor = batch.next_cursor
        }
      } catch {
        // ignore transient polling errors
      } finally {
        if (active) timer = window.setTimeout(poll, 1500)
      }
    }

    void poll()
    return () => {
      active = false
      if (timer) window.clearTimeout(timer)
    }
  }, [currentTask?.id])

  const canPlanReview = currentTask?.status === 'PLAN_REVIEW' && !!currentTask.plan_result
  const canMarkDone = currentTask?.status === 'REVIEW'

  const normalizedPlan = useMemo(() => normalizePlanResult(currentTask?.plan_result), [currentTask?.plan_result])
  const questionList = useMemo(() => normalizedPlan.questions, [normalizedPlan])
  const allQuestionsAnswered = useMemo(() => isPlanAnswersComplete(questionList, answers), [answers, questionList])
  const logEntries = useMemo(() => events.map((event, index) => toLogEntry(event, index)), [events])
  const groupCounts = useMemo(() => {
    const counts: Record<TaskEventDisplayGroup, number> = {
      command: 0,
      output: 0,
      result: 0,
      timeout: 0,
      artifact: 0,
      protocol: 0,
    }
    for (const entry of logEntries) counts[entry.group] += 1
    return counts
  }, [logEntries])
  const filteredEntries = useMemo(
    () => logEntries.filter((entry) => groupFilters[entry.group]),
    [groupFilters, logEntries],
  )
  const logBlocks = useMemo(() => mergeLogEntries(filteredEntries), [filteredEntries])

  useEffect(() => {
    setAnswers((prev) => {
      const next = deriveInitialAnswers(questionList, prev)
      const prevKeys = Object.keys(prev)
      const nextKeys = Object.keys(next)
      if (prevKeys.length !== nextKeys.length) return next
      for (const key of nextKeys) {
        if (prev[key] !== next[key]) return next
      }
      return prev
    })
  }, [questionList])

  useEffect(() => {
    const allowedKeys = new Set(logBlocks.map((block) => block.key))
    setExpandedRawBlocks((prev) => {
      let changed = false
      const next = new Set<string>()
      for (const key of prev) {
        if (!allowedKeys.has(key)) {
          changed = true
          continue
        }
        next.add(key)
      }
      return changed ? next : prev
    })
  }, [logBlocks])

  useEffect(() => {
    if (!followLogs) return
    const node = logBoxRef.current
    if (!node) return
    node.scrollTop = node.scrollHeight
  }, [followLogs, logBlocks])

  function onLogScroll() {
    const node = logBoxRef.current
    if (!node) return
    const distanceToBottom = node.scrollHeight - node.scrollTop - node.clientHeight
    const isNearBottom = distanceToBottom <= FOLLOW_BOTTOM_THRESHOLD
    if (isNearBottom) {
      if (!followLogs) setFollowLogs(true)
      return
    }
    if (followLogs) setFollowLogs(false)
  }

  function resumeLogFollow() {
    const node = logBoxRef.current
    if (node) node.scrollTop = node.scrollHeight
    setFollowLogs(true)
  }

  function toggleGroupFilter(group: TaskEventDisplayGroup) {
    setGroupFilters((prev) => ({ ...prev, [group]: !prev[group] }))
  }

  function toggleRawBlock(blockKey: string) {
    setExpandedRawBlocks((prev) => {
      const next = new Set(prev)
      if (next.has(blockKey)) next.delete(blockKey)
      else next.add(blockKey)
      return next
    })
  }

  async function confirmPlan() {
    if (!currentTask) return
    await api.confirmPlan(currentTask.id, answers)
    await onChanged()
  }

  async function revisePlan() {
    if (!currentTask || !feedback.trim()) return
    await api.revisePlan(currentTask.id, feedback.trim())
    setFeedback('')
    await onChanged()
  }

  async function retryTask() {
    if (!currentTask) return
    await api.retryTask(currentTask.id)
    await onChanged()
  }

  async function cancelTask() {
    if (!currentTask) return
    await api.cancelTask(currentTask.id)
    await onChanged()
  }

  async function markDone() {
    if (!currentTask) return
    await api.markDone(currentTask.id)
    await onChanged()
  }

  if (!currentTask) return null

  return (
    <aside className="drawer-mask" onClick={onClose}>
      <section className="drawer" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-header">
          <h3>{currentTask.title}</h3>
          <button className="icon-btn" onClick={onClose}>
            关闭
          </button>
        </header>

        <div className="drawer-row">
          <strong>任务 ID:</strong> {currentTask.id}
        </div>
        <div className="drawer-row">
          <strong>状态:</strong> {currentTask.status}
        </div>
        <div className="drawer-row">
          <strong>PR:</strong>{' '}
          {currentTask.pr_url ? (
            <a href={currentTask.pr_url} target="_blank" rel="noreferrer">
              {currentTask.pr_url}
            </a>
          ) : (
            '-'
          )}
        </div>
        {!!currentTask.error_message && (
          <div className="drawer-error">
            <strong>错误:</strong> {currentTask.error_message}
          </div>
        )}

        {canPlanReview && (
          <div className="plan-panel">
            <h4>Plan 审批</h4>
            {renderPlanDetailBlocks(normalizedPlan)}
            <PlanChoiceCard
              title="Claude 的问题（请回答后再确认）"
              questions={questionList}
              answers={answers}
              onSelect={(questionId, optionKey) => setAnswers((prev) => ({ ...prev, [questionId]: optionKey }))}
              showConfirmHint
              className="plan-choice-card-panel"
            />
            <div className="drawer-actions">
              <button className="button button-primary" onClick={confirmPlan} disabled={!allQuestionsAnswered}>
                确认并执行
              </button>
            </div>
            <textarea
              className="textarea"
              placeholder="输入反馈后让 Plan 重新生成"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
            />
            <div className="drawer-actions">
              <button className="button" onClick={revisePlan}>
                修改反馈
              </button>
            </div>
          </div>
        )}

        <div className="drawer-actions">
          {canMarkDone && (
            <button className="button button-primary" onClick={markDone}>
              标记完成
            </button>
          )}
          <button className="button" onClick={retryTask}>
            重试
          </button>
          <button className="button button-danger" onClick={cancelTask}>
            取消任务
          </button>
        </div>

        <h4>日志流</h4>
        <div className="log-toolbar">
          <div className="log-filters">
            {GROUP_FILTER_OPTIONS.map((option) => (
              <button
                key={option.group}
                type="button"
                className={`log-filter-chip ${groupFilters[option.group] ? 'log-filter-chip-active' : ''}`}
                onClick={() => toggleGroupFilter(option.group)}
              >
                {option.label}
                <span className="log-filter-count">{groupCounts[option.group]}</span>
              </button>
            ))}
          </div>
          <span className={`log-follow-state ${followLogs ? 'log-follow-state-on' : 'log-follow-state-off'}`}>
            {followLogs ? '自动跟随中' : '已暂停跟随'}
          </span>
        </div>
        <div className="log-panel">
          <div className="log-box" ref={logBoxRef} onScroll={onLogScroll}>
            {logBlocks.length === 0 ? (
              <div className="log-empty">{events.length === 0 ? '暂无日志' : '当前筛选无日志'}</div>
            ) : (
              logBlocks.map((block) => {
                const expanded = expandedRawBlocks.has(block.key)
                return (
                  <div className={`log-item log-item-${block.group}`} key={block.key}>
                    <div className="log-item-head">
                      <span className="log-time">{block.time}</span>
                      {block.count > 1 && <span className="log-merge-count">x{block.count}</span>}
                    </div>
                    <pre className="log-line">{block.message}</pre>
                    <button type="button" className="log-raw-toggle" onClick={() => toggleRawBlock(block.key)}>
                      {expanded ? '收起原始' : '查看原始'}
                    </button>
                    {expanded && <pre className="log-raw">{formatRawEntries(block.rawEntries)}</pre>}
                  </div>
                )
              })
            )}
          </div>
          {!followLogs && logBlocks.length > 0 && (
            <button type="button" className="log-follow-btn" onClick={resumeLogFollow}>
              回到底部并继续跟随
            </button>
          )}
        </div>
      </section>
    </aside>
  )
}
