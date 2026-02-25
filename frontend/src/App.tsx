import { useEffect, useState } from 'react'
import BoardPage from './pages/BoardPage'
import TaskDetailPage from './pages/TaskDetailPage'

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

  if (route.view === 'task' && route.taskId) {
    return (
      <TaskDetailPage
        taskId={route.taskId}
        onBack={() => window.history.back()}
        onBackFallback={() => navigate('/')}
      />
    )
  }

  return <BoardPage onOpenTask={(taskId) => navigate(`/task/${encodeURIComponent(taskId)}`)} />
}
