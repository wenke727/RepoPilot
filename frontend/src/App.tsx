import { useEffect, useState } from 'react'
import { api, AuthRequiredError, clearAuthToken, getAuthToken } from './api/client'
import type { ExecMode } from './types'
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

export default function App() {
  const [route, setRoute] = useState<RouteState>(() => parseRoute(window.location.pathname))
  const [execMode, setExecModeState] = useState<ExecMode>('AGENTIC')
  const [authChecked, setAuthChecked] = useState(false)
  const [needLogin, setNeedLogin] = useState(false)

  useEffect(() => {
    api
      .getExecMode()
      .then((r) => {
        setExecModeState(r.exec_mode)
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
          api.getExecMode().then((r) => setExecModeState(r.exec_mode)).catch(() => {})
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
