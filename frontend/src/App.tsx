import { useEffect, useState } from 'react'
import { api, AuthRequiredError, clearAuthToken, getAuthToken } from './api/client'
import type { AgentDriver, ExecMode } from './types'
import BoardPage from './pages/BoardPage'
import TaskDetailPage from './pages/TaskDetailPage'
import LoginPage from './pages/LoginPage'

interface RouteState {
  view: 'board' | 'task'
  taskId?: string
}

function parseRoute(pathname: string): RouteState {
  const taskMatch = pathname.match(/^\/task\/([^/]+)$/)
  if (taskMatch) {
    return { view: 'task', taskId: decodeURIComponent(taskMatch[1]) }
  }
  return { view: 'board' }
}

function navigate(pathname: string, replace = false) {
  if (replace) window.history.replaceState({}, '', pathname)
  else window.history.pushState({}, '', pathname)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function describeError(error: unknown): string {
  if (!(error instanceof Error)) return 'unknown error'
  const raw = error.message || 'unknown error'
  try {
    const parsed = JSON.parse(raw)
    const detail = parsed?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (typeof detail?.message === 'string' && detail.message.trim()) return detail.message
  } catch {
    // keep raw text
  }
  return raw
}

export default function App() {
  const [route, setRoute] = useState<RouteState>(() => parseRoute(window.location.pathname))
  const [execMode, setExecModeState] = useState<ExecMode>('AGENTIC')
  const [agentDriver, setAgentDriverState] = useState<AgentDriver>('CLAUDE_KIMI')
  const [authChecked, setAuthChecked] = useState(false)
  const [needLogin, setNeedLogin] = useState(false)

  useEffect(() => {
    Promise.all([api.getExecMode(), api.getAgentDriver()])
      .then(([execResp, driverResp]) => {
        setExecModeState(execResp.exec_mode)
        setAgentDriverState(driverResp.agent_driver)
        setNeedLogin(false)
      })
      .catch((e) => {
        setNeedLogin(e instanceof AuthRequiredError)
      })
      .finally(() => setAuthChecked(true))
  }, [])

  useEffect(() => {
    const onAuthRequired = () => setNeedLogin(true)
    window.addEventListener('auth-required', onAuthRequired)
    return () => window.removeEventListener('auth-required', onAuthRequired)
  }, [])

  const setExecMode = (mode: ExecMode) => {
    api.setExecMode(mode).then((r) => setExecModeState(r.exec_mode)).catch(() => {})
  }
  const setAgentDriver = (driver: AgentDriver) => {
    api
      .setAgentDriver(driver)
      .then((r) => setAgentDriverState(r.agent_driver))
      .catch((e) => {
        window.alert(`切换驱动失败：${describeError(e)}`)
      })
  }

  useEffect(() => {
    const onPopState = () => setRoute(parseRoute(window.location.pathname))
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  useEffect(() => {
    if (route.view === 'board' && window.location.pathname !== '/') {
      navigate('/', true)
    }
  }, [route.view])

  if (!authChecked) {
    return (
      <div className="login-page" style={{ alignItems: "center", justifyContent: "center" }}>
        <p style={{ color: "var(--muted)" }}>加载中…</p>
      </div>
    )
  }
  if (needLogin) {
    return (
      <LoginPage
        onSuccess={() => {
          setNeedLogin(false)
          Promise.all([api.getExecMode(), api.getAgentDriver()])
            .then(([execResp, driverResp]) => {
              setExecModeState(execResp.exec_mode)
              setAgentDriverState(driverResp.agent_driver)
            })
            .catch(() => {})
        }}
      />
    )
  }

  const execModeBar = (
    <header className="app-exec-mode-bar">
      <span className="app-exec-mode-label">执行模式</span>
      <div className="app-exec-mode-toggle">
        <button
          type="button"
          className={execMode === 'AGENTIC' ? 'app-exec-mode-btn active' : 'app-exec-mode-btn'}
          onClick={() => setExecMode('AGENTIC')}
        >
          AGENTIC
        </button>
        <button
          type="button"
          className={execMode === 'FIXED' ? 'app-exec-mode-btn active' : 'app-exec-mode-btn'}
          onClick={() => setExecMode('FIXED')}
        >
          FIXED
        </button>
      </div>
      <span className="app-exec-mode-label">驱动</span>
      <div className="app-agent-driver-toggle">
        <button
          type="button"
          className={agentDriver === 'CLAUDE' ? 'app-exec-mode-btn active' : 'app-exec-mode-btn'}
          onClick={() => setAgentDriver('CLAUDE')}
        >
          CLAUDE
        </button>
        <button
          type="button"
          className={agentDriver === 'CLAUDE_KIMI' ? 'app-exec-mode-btn active' : 'app-exec-mode-btn'}
          onClick={() => setAgentDriver('CLAUDE_KIMI')}
        >
          KIMI
        </button>
        <button
          type="button"
          className={agentDriver === 'CLAUDE_GLM' ? 'app-exec-mode-btn active' : 'app-exec-mode-btn'}
          onClick={() => setAgentDriver('CLAUDE_GLM')}
        >
          GLM
        </button>
        <button type="button" className="app-exec-mode-btn app-exec-mode-btn-disabled" disabled>
          CURSOR（预留）
        </button>
      </div>
      {getAuthToken() && (
        <button
          type="button"
          className="app-logout-btn"
          onClick={() => {
            clearAuthToken()
            setNeedLogin(true)
          }}
        >
          退出
        </button>
      )}
    </header>
  )

  if (route.view === 'task' && route.taskId) {
    return (
      <>
        {execModeBar}
        <TaskDetailPage
          taskId={route.taskId}
          onBack={() => window.history.back()}
          onBackFallback={() => navigate('/')}
        />
      </>
    )
  }

  return (
    <>
      {execModeBar}
      <BoardPage onOpenTask={(taskId) => navigate(`/task/${encodeURIComponent(taskId)}`)} />
    </>
  )
}
