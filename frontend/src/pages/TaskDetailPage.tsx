import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from '../api/client'
import type { Task, TaskEvent, TaskEventDisplay, TaskEventDisplayGroup } from '../types'

interface Props {
  taskId: string
  onBack: () => void
  onBackFallback: () => void
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

type ChatRole = 'user' | 'assistant' | 'system'

interface ChatBlock extends LogBlock {
  role: ChatRole
  isRangedSeq: boolean
}

interface ActivityDigest {
  summary: string
  detailLines: string[]
}

const LOG_EVENT_LIMIT = 2000
const LOG_BLOCK_LIMIT = 300
const FOLLOW_BOTTOM_THRESHOLD = 24
const ACTIVITY_LINE_PATTERN =
  /^(Explored\b|Listed files\b|Read\b|Searched for\b|Background terminal finished with\b|Success\b|Opened\b|Clicked\b|Ran\b)/i
const ACTIVITY_MAX_LINES = 36
const ACTIVITY_MAX_LINE_LENGTH = 260

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

function toChatRole(group: TaskEventDisplayGroup): ChatRole {
  if (group === 'command') return 'user'
  if (group === 'output' || group === 'result') return 'assistant'
  return 'system'
}

function toBubbleTextClass(group: TaskEventDisplayGroup): string {
  if (group === 'output' || group === 'artifact' || group === 'protocol') {
    return 'chat-bubble-text chat-bubble-text-mono'
  }
  return 'chat-bubble-text'
}

function shouldRenderMarkdown(group: TaskEventDisplayGroup): boolean {
  return group === 'output' || group === 'result'
}

function toActivityDigest(message: string): ActivityDigest | null {
  if (!message || message.includes('```')) return null
  const lines = message
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
  if (lines.length < 2 || lines.length > ACTIVITY_MAX_LINES) return null
  if (lines.some((line) => line.length > ACTIVITY_MAX_LINE_LENGTH)) return null

  const matchedIndexes: number[] = []
  for (let index = 0; index < lines.length; index += 1) {
    if (ACTIVITY_LINE_PATTERN.test(lines[index])) matchedIndexes.push(index)
  }
  if (matchedIndexes.length < 2) return null
  if (matchedIndexes.length < Math.ceil(lines.length * 0.5)) return null

  const summaryIndex = matchedIndexes[0]
  const detailLines = lines.filter((_, index) => index !== summaryIndex)
  return { summary: lines[summaryIndex], detailLines }
}

function formatRawEntries(entries: LogRawEntry[]): string {
  return entries
    .map((entry, index) => `${index > 0 ? '\n\n-----\n' : ''}#${entry.seq}\n${entry.raw}`)
    .join('')
}

export default function TaskDetailPage({ taskId, onBack, onBackFallback }: Props) {
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [currentTask, setCurrentTask] = useState<Task | null>(null)
  const [feedback, setFeedback] = useState('')
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [groupFilters, setGroupFilters] = useState<Record<TaskEventDisplayGroup, boolean>>(DEFAULT_GROUP_FILTERS)
  const [followLogs, setFollowLogs] = useState(true)
  const [expandedRawBlocks, setExpandedRawBlocks] = useState<Set<string>>(new Set())
  const [expandedActivityBlocks, setExpandedActivityBlocks] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [planSheetOpen, setPlanSheetOpen] = useState(false)
  const logBoxRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    setCurrentTask(null)
    setEvents([])
    setFeedback('')
    setAnswers({})
    setGroupFilters(DEFAULT_GROUP_FILTERS)
    setFollowLogs(true)
    setExpandedRawBlocks(new Set())
    setExpandedActivityBlocks(new Set())
    setLoading(true)
    setError('')
    setPlanSheetOpen(false)
  }, [taskId])

  useEffect(() => {
    const activeTaskId = taskId
    let active = true
    let localCursor = 0
    let timer: number | undefined

    async function poll() {
      if (!active) return
      try {
        const [taskResp, batch] = await Promise.all([
          api.getTask(activeTaskId),
          api.getTaskEvents(activeTaskId, localCursor),
        ])
        if (!active) return
        setCurrentTask(taskResp)
        setError('')
        if (batch.events.length > 0) {
          setEvents((prev) => {
            const merged = [...prev, ...batch.events]
            if (merged.length <= LOG_EVENT_LIMIT) return merged
            return merged.slice(-LOG_EVENT_LIMIT)
          })
          localCursor = batch.next_cursor
        }
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : '任务加载失败')
      } finally {
        if (active) {
          setLoading(false)
          timer = window.setTimeout(poll, 1500)
        }
      }
    }

    void poll()
    return () => {
      active = false
      if (timer) window.clearTimeout(timer)
    }
  }, [taskId])

  const canPlanReview = currentTask?.status === 'PLAN_REVIEW' && !!currentTask.plan_result
  const canMarkDone = currentTask?.status === 'REVIEW'

  const questionList = useMemo(() => currentTask?.plan_result?.questions ?? [], [currentTask])
  const allQuestionsAnswered = useMemo(() => {
    if (questionList.length === 0) return true
    return questionList.every((q) => q.options.some((opt) => opt.key === answers[q.id]))
  }, [answers, questionList])
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
  const chatBlocks = useMemo<ChatBlock[]>(
    () =>
      logBlocks.map((block) => ({
        ...block,
        role: toChatRole(block.group),
        isRangedSeq: block.seqStart !== block.seqEnd,
      })),
    [logBlocks],
  )

  useEffect(() => {
    setAnswers((prev) => {
      const next: Record<string, string> = {}
      let changed = false
      for (const q of questionList) {
        const selected = prev[q.id]
        const selectedValid = q.options.some((opt) => opt.key === selected)
        if (selectedValid) {
          next[q.id] = selected
          continue
        }
        const recommended = q.recommended_option_key
        const recommendedValid = q.options.some((opt) => opt.key === recommended)
        if (recommendedValid && recommended) {
          next[q.id] = recommended
          changed = true
          continue
        }
        if (selected) changed = true
      }
      const prevKeys = Object.keys(prev)
      const nextKeys = Object.keys(next)
      if (prevKeys.length !== nextKeys.length) return next
      for (const key of nextKeys) {
        if (prev[key] !== next[key]) return next
      }
      return changed ? next : prev
    })
  }, [questionList])

  useEffect(() => {
    if (!canPlanReview) setPlanSheetOpen(false)
  }, [canPlanReview])

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
    setExpandedActivityBlocks((prev) => {
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

  function toggleActivityBlock(blockKey: string) {
    setExpandedActivityBlocks((prev) => {
      const next = new Set(prev)
      if (next.has(blockKey)) next.delete(blockKey)
      else next.add(blockKey)
      return next
    })
  }

  async function confirmPlan() {
    if (!currentTask) return
    await api.confirmPlan(currentTask.id, answers)
    setCurrentTask(await api.getTask(taskId))
  }

  async function revisePlan() {
    if (!currentTask || !feedback.trim()) return
    await api.revisePlan(currentTask.id, feedback.trim())
    setFeedback('')
    setCurrentTask(await api.getTask(taskId))
  }

  async function retryTask() {
    if (!currentTask) return
    await api.retryTask(currentTask.id)
    setCurrentTask(await api.getTask(taskId))
  }

  async function cancelTask() {
    if (!currentTask) return
    await api.cancelTask(currentTask.id)
    setCurrentTask(await api.getTask(taskId))
  }

  async function markDone() {
    if (!currentTask) return
    await api.markDone(currentTask.id)
    setCurrentTask(await api.getTask(taskId))
  }

  function renderPlanPanel(panelClassName: string) {
    if (!canPlanReview) return null
    const plan = currentTask?.plan_result
    const hasEnhancedDetails = plan && (
      plan.steps?.length > 0 ||
      plan.risks?.length > 0 ||
      plan.affected_files?.length > 0 ||
      plan.new_dependencies?.length > 0 ||
      plan.estimated_time ||
      plan.validation ||
      plan.rollback
    )

    return (
      <div className={`plan-panel ${panelClassName}`}>
        <h4>Plan 审批</h4>
        <p>{plan?.summary || '无摘要'}</p>

        {/* Enhanced Plan Details */}
        {hasEnhancedDetails && (
          <div className="plan-details-section">
            {plan?.steps && plan.steps.length > 0 && (
              <div className="plan-detail-block">
                <strong>实施步骤:</strong>
                <ol className="plan-steps-list">
                  {plan.steps.map((step, i) => (
                    <li key={i}>{step}</li>
                  ))}
                </ol>
              </div>
            )}

            {plan?.risks && plan.risks.length > 0 && (
              <div className="plan-detail-block">
                <strong>风险评估:</strong>
                <ul className="plan-risks-list">
                  {plan.risks.map((risk, i) => (
                    <li key={i} className="plan-risk-item">{risk}</li>
                  ))}
                </ul>
              </div>
            )}

            {plan?.affected_files && plan.affected_files.length > 0 && (
              <div className="plan-detail-block">
                <strong>涉及文件:</strong>
                <div className="plan-files-list">
                  {plan.affected_files.map((file, i) => (
                    <code key={i} className="plan-file-item">{file}</code>
                  ))}
                </div>
              </div>
            )}

            {plan?.new_dependencies && plan.new_dependencies.length > 0 && (
              <div className="plan-detail-block">
                <strong>新增依赖:</strong>
                <div className="plan-deps-list">
                  {plan.new_dependencies.map((dep, i) => (
                    <span key={i} className="plan-dep-item">{dep}</span>
                  ))}
                </div>
              </div>
            )}

            {plan?.estimated_time && (
              <div className="plan-detail-block">
                <strong>预计执行时间:</strong>
                <span className="plan-meta-value">{plan.estimated_time}</span>
              </div>
            )}

            {plan?.validation && (
              <div className="plan-detail-block">
                <strong>验证方法:</strong>
                <p className="plan-meta-text">{plan.validation}</p>
              </div>
            )}

            {plan?.rollback && (
              <div className="plan-detail-block">
                <strong>回滚方式:</strong>
                <p className="plan-meta-text">{plan.rollback}</p>
              </div>
            )}
          </div>
        )}

        {/* Decision Questions */}
        {questionList.map((q) => (
          <div className="plan-question" key={q.id}>
            <div className="plan-question-title">{q.title}</div>
            <div className="muted">{q.question}</div>
            <div className="plan-options">
              {q.options.map((opt) => (
                <button
                  key={opt.key}
                  className={`pill ${answers[q.id] === opt.key ? 'pill-active' : ''}`}
                  onClick={() => setAnswers((prev) => ({ ...prev, [q.id]: opt.key }))}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        ))}
        {!allQuestionsAnswered && questionList.length > 0 && (
          <div className="plan-answer-hint">请先完成所有选项后再确认执行。</div>
        )}
        <div className="task-detail-actions">
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
        <div className="task-detail-actions">
          <button className="button" onClick={revisePlan} disabled={!feedback.trim()}>
            修改反馈
          </button>
          <button className="button button-danger" onClick={cancelTask}>
            放弃 Plan
          </button>
        </div>
      </div>
    )
  }

  if (!currentTask) {
    return (
      <div className="page">
        <section className="task-detail-page">
          <div className="task-detail-header">
            <button className="button" onClick={onBack}>返回上一页</button>
            <button className="button" onClick={onBackFallback}>返回任务看板</button>
          </div>
          {loading ? <div className="muted">任务加载中...</div> : <div className="alert">{error || '任务不存在或暂时不可用'}</div>}
        </section>
      </div>
    )
  }

  return (
    <div className="page">
      <section className={`task-detail-page ${canPlanReview ? 'task-detail-page-plan-review' : ''}`}>
        <header className="task-detail-header">
          <div className="task-detail-title-wrap">
            <h3>{currentTask.title}</h3>
          </div>
          <div className="task-detail-nav-actions">
            <button className="button" onClick={onBack}>返回上一页</button>
            <button className="button" onClick={onBackFallback}>返回任务看板</button>
          </div>
        </header>

        <div className="task-detail-meta-grid">
          <div className="task-detail-row">
            <strong>任务 ID</strong>
            <span>{currentTask.id}</span>
          </div>
          <div className="task-detail-row">
            <strong>状态</strong>
            <span className="task-status-pill">{currentTask.status}</span>
          </div>
          <div className="task-detail-row">
            <strong>PR</strong>
            {currentTask.pr_url ? (
              <a href={currentTask.pr_url} target="_blank" rel="noreferrer">
                {currentTask.pr_url}
              </a>
            ) : (
              <span>-</span>
            )}
          </div>
        </div>
        {!!currentTask.error_message && (
          <div className="task-detail-error">
            <strong>错误:</strong> {currentTask.error_message}
          </div>
        )}
        {error && <div className="task-detail-error">
          <strong>轮询异常:</strong> {error}
        </div>}

        {canPlanReview && (
          <div className="plan-sticky-shell">
            {renderPlanPanel('plan-sticky-panel')}
          </div>
        )}

        <div className="task-detail-actions task-detail-actions-main">
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

        <h4 className="chat-section-title">日志流</h4>
        <div className="log-toolbar log-toolbar-sticky">
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
          <div className="log-box log-chat-box" ref={logBoxRef} onScroll={onLogScroll}>
            {chatBlocks.length === 0 ? (
              <div className="log-empty">{events.length === 0 ? '暂无日志' : '当前筛选无日志'}</div>
            ) : (
              <div className="chat-stream">
                {chatBlocks.map((block) => {
                  const seqRange =
                    block.seqStart === block.seqEnd ? `${block.seqStart}` : `${block.seqStart}-${block.seqEnd}`
                  const expanded = expandedRawBlocks.has(block.key)
                  const markdownEnabled = shouldRenderMarkdown(block.group)
                  const activityDigest = markdownEnabled ? null : toActivityDigest(block.message)
                  const activityExpanded = expandedActivityBlocks.has(block.key)
                  const bubbleTextClass = toBubbleTextClass(block.group)
                  return (
                    <div className={`chat-row chat-row-${block.role}`} key={block.key}>
                      <div className={`chat-bubble chat-bubble-${block.role} chat-bubble-group-${block.group}`}>
                        <div className="chat-bubble-head">
                          <span className="chat-time">{block.time}</span>
                          <span className="chat-tag">{block.label}</span>
                          <span className="chat-seq">{seqRange}</span>
                          {block.count > 1 && <span className="chat-merge-label">合并{block.count}条</span>}
                          <button
                            type="button"
                            className={`chat-raw-toggle ${expanded ? 'chat-raw-toggle-expanded' : ''}`}
                            onClick={() => toggleRawBlock(block.key)}
                            title={expanded ? '收起原始' : '查看原始'}
                            aria-label={expanded ? '收起原始' : '查看原始'}
                          >
                            {'>'}
                          </button>
                        </div>
                        {block.isRangedSeq && (
                          <div className="chat-seq-hint">
                            序号跨度表示中间有其他事件（可能被筛选或合并），不代表中断。
                          </div>
                        )}
                        {activityDigest ? (
                          <div className="chat-activity">
                            <div className="chat-activity-head">
                              <span className="chat-activity-summary">{activityDigest.summary}</span>
                              {activityDigest.detailLines.length > 0 && (
                                <button
                                  type="button"
                                  className="chat-activity-more"
                                  onClick={() => toggleActivityBlock(block.key)}
                                >
                                  {activityExpanded ? '收起' : '更多'}
                                </button>
                              )}
                            </div>
                            {activityExpanded && activityDigest.detailLines.length > 0 && (
                              <div className="chat-activity-lines">
                                {activityDigest.detailLines.map((line, lineIndex) => (
                                  <div className="chat-activity-line" key={`${block.key}-activity-${lineIndex}`}>
                                    {line}
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        ) : markdownEnabled ? (
                          <div className="chat-bubble-markdown">
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm]}
                              components={{
                                a: ({ href, children, ...props }) => (
                                  <a href={href} target="_blank" rel="noreferrer noopener" {...props}>
                                    {children}
                                  </a>
                                ),
                              }}
                            >
                              {block.message}
                            </ReactMarkdown>
                          </div>
                        ) : (
                          <pre className={bubbleTextClass}>{block.message}</pre>
                        )}
                        {expanded && <pre className="log-raw">{formatRawEntries(block.rawEntries)}</pre>}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
          {!followLogs && chatBlocks.length > 0 && (
            <button type="button" className="log-follow-btn" onClick={resumeLogFollow}>
              回到底部并继续跟随
            </button>
          )}
        </div>
      </section>

      {canPlanReview && (
        <div className="plan-mobile-dock">
          <div className="plan-mobile-dock-text">
            <strong>Plan 审批待处理</strong>
            <span>{currentTask.plan_result?.summary || '请确认执行选项'}</span>
          </div>
          <button type="button" className="button button-primary" onClick={() => setPlanSheetOpen(true)}>
            展开 Plan 选项
          </button>
        </div>
      )}

      {canPlanReview && planSheetOpen && (
        <div className="plan-mobile-sheet-mask" onClick={() => setPlanSheetOpen(false)}>
          <section className="plan-mobile-sheet" onClick={(e) => e.stopPropagation()}>
            <header className="plan-mobile-sheet-header">
              <strong>Plan 审批</strong>
              <button type="button" className="icon-btn" onClick={() => setPlanSheetOpen(false)}>
                关闭
              </button>
            </header>
            {renderPlanPanel('plan-mobile-sheet-panel')}
          </section>
        </div>
      )}
    </div>
  )
}
