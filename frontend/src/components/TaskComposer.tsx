import { useMemo, useState, type KeyboardEvent } from 'react'
import { api, AuthRequiredError } from '../api/client'
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

function getVoiceUnsupportedMessage(): string {
  const hasGetUserMedia = Boolean(navigator.mediaDevices?.getUserMedia)
  const hasMediaRecorder = typeof MediaRecorder !== "undefined"
  const isSecureContext =
    typeof window !== "undefined" &&
    (window.isSecureContext ||
      (window.location?.protocol === "https:" || /^localhost$|^127\./.test(window.location?.hostname ?? "")))
  if (!isSecureContext) {
    return "语音输入需要安全连接。请使用 https:// 访问本页面后再试（手机访问必须用 HTTPS）。"
  }
  if (!hasGetUserMedia) {
    return "当前浏览器不支持麦克风访问。请使用 HTTPS 打开本页，或关闭系统「锁定模式」后重试。"
  }
  if (!hasMediaRecorder) {
    return "当前浏览器不支持录音格式。请使用 Chrome、Edge 或 Safari 桌面版，或 iOS 14+ 的 Safari。"
  }
  return "当前浏览器不支持录音，请换用支持的浏览器或使用 HTTPS 访问。"
}

function getAudioFileInfo(mime: string | undefined): { name: string; type: string } {
  if (!mime) {
    return { name: "voice-input.webm", type: "audio/webm" }
  }
  if (mime.startsWith("audio/webm")) {
    return { name: "voice-input.webm", type: "audio/webm" }
  }
  if (mime.startsWith("audio/mp4") || mime.startsWith("audio/x-m4a") || mime.startsWith("audio/m4a")) {
    return { name: "voice-input.m4a", type: "audio/mp4" }
  }
  if (mime.startsWith("audio/mpeg")) {
    return { name: "voice-input.mp3", type: "audio/mpeg" }
  }
  if (mime.startsWith("audio/wav") || mime.startsWith("audio/x-wav")) {
    return { name: "voice-input.wav", type: "audio/wav" }
  }
  return { name: "voice-input.webm", type: "audio/webm" }
}

export default function TaskComposer({ selectedRepoId, onCreate }: Props) {
  const [prompt, setPrompt] = useState('')
  const [mode, setMode] = useState<TaskMode>('PLAN')
  const permissionMode: PermissionMode = 'BYPASS'
  const priority = 0
  const [submitting, setSubmitting] = useState(false)
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)

  async function onVoiceInput() {
    if (recording || transcribing) return
    const hasGetUserMedia = Boolean(navigator.mediaDevices?.getUserMedia)
    const hasMediaRecorder = typeof MediaRecorder !== "undefined"
    if (!hasGetUserMedia || !hasMediaRecorder) {
      window.alert(getVoiceUnsupportedMessage())
      return
    }

    let stream: MediaStream | null = null
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      const chunks: BlobPart[] = []
      setRecording(true)
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.push(event.data)
      }

      recorder.start()
      await new Promise<void>((resolve) => {
        window.setTimeout(() => {
          recorder.stop()
          resolve()
        }, 5000)
      })
      await new Promise<void>((resolve) => {
        recorder.onstop = () => resolve()
      })

      setRecording(false)
      setTranscribing(true)
      const { name, type } = getAudioFileInfo(recorder.mimeType)
      const blob = new Blob(chunks, { type })
      const audioFile = new File([blob], name, { type })
      const result = await api.transcribeAudio(audioFile, 'zh')
      const nextPrompt = [prompt.trim(), result.text.trim()].filter(Boolean).join('\n')
      setPrompt(nextPrompt)
    } catch (error) {
      console.error(error)
      if (error instanceof AuthRequiredError) return
      const msg = error instanceof Error ? error.message : ""
      const hint =
        msg && !msg.includes("getUserMedia")
          ? `语音转写失败：${msg}`
          : "语音输入失败，请检查麦克风权限或 OpenAI 配置。"
      window.alert(hint)
    } finally {
      setRecording(false)
      setTranscribing(false)
      stream?.getTracks().forEach((track) => track.stop())
    }
  }

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
        <button
          className={recording ? 'icon-btn composer-mic is-recording' : 'icon-btn composer-mic'}
          type="button"
          aria-label="语音输入"
          disabled={recording || transcribing}
          onClick={() => void onVoiceInput()}
        >
          {recording ? '录音中' : transcribing ? '识别中' : '语音'}
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
