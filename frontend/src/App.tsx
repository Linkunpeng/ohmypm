import { useEffect, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from 'next-themes'
import { createBrowserRouter, RouterProvider } from 'react-router'

import { AppShell } from '@/components/AppShell'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { ApiError, setUnauthorizedHandler } from '@/lib/api'
import { captureTokenFromHash, getToken } from '@/lib/auth'
import { Dashboard } from '@/pages/Dashboard'
import { Artifacts, Decisions, KnowledgePage, SearchPage } from '@/pages/Library'
import { Login } from '@/pages/Login'
import { Projects, ProjectView } from '@/pages/Projects'
import { Runs, RunView } from '@/pages/Runs'
import { Tasks } from '@/pages/Tasks'
import { TaskView } from '@/pages/TaskView'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 2000,
      retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
    },
  },
})

function buildRouter(onLogout: () => void) {
  return createBrowserRouter([
    {
      path: '/',
      element: <AppShell onLogout={onLogout} />,
      children: [
        { index: true, element: <Dashboard /> },
        { path: 'projects', element: <Projects /> },
        { path: 'projects/:id', element: <ProjectView /> },
        { path: 'tasks', element: <Tasks /> },
        { path: 'tasks/:id', element: <TaskView /> },
        { path: 'runs', element: <Runs /> },
        { path: 'runs/:id', element: <RunView /> },
        { path: 'decisions', element: <Decisions /> },
        { path: 'artifacts', element: <Artifacts /> },
        { path: 'knowledge', element: <KnowledgePage /> },
        { path: 'search', element: <SearchPage /> },
        { path: '*', element: <div className="text-muted-foreground">Page not found.</div> },
      ],
    },
  ])
}

export default function App() {
  const [authed, setAuthed] = useState(() => {
    captureTokenFromHash()
    return Boolean(getToken())
  })
  const [router] = useState(() => buildRouter(() => setAuthed(false)))

  useEffect(() => {
    setUnauthorizedHandler(() => setAuthed(false))
  }, [])

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          {authed ? (
            <RouterProvider router={router} />
          ) : (
            <Login
              onLogin={() => {
                queryClient.clear()
                setAuthed(true)
              }}
            />
          )}
          <Toaster richColors />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  )
}
