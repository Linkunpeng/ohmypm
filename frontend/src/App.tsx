import { useQuery } from "@tanstack/react-query";
import { createBrowserRouter, isRouteErrorResponse, Link, Outlet, useRouteError } from "react-router";
import { RouterProvider } from "react-router/dom";

import { AppShell } from "@/components/AppShell";
import { Empty, ErrorNotice, Loading } from "@/components/common";
import { ApiError, api } from "@/lib/api";
import { queryKeys } from "@/lib/hooks";
import { ContextPage } from "@/pages/ContextPage";
import { Dashboard } from "@/pages/Dashboard";
import { EntryPage } from "@/pages/EntryPage";
import { ProjectPage } from "@/pages/ProjectPage";
import { SearchPage } from "@/pages/SearchPage";
import { SignIn } from "@/pages/SignIn";

function Layout() {
  // The project list doubles as the access check: 401 means "not signed in".
  const { error, isLoading } = useQuery({ queryKey: queryKeys.projects, queryFn: () => api.projects() });
  if (error instanceof ApiError && error.status === 401) return <SignIn />;
  return (
    <AppShell>
      {isLoading ? <Loading /> : error ? <ErrorNotice error={error} what="ohmypm" /> : <Outlet />}
    </AppShell>
  );
}

function RouteError() {
  const error = useRouteError();
  return (
    <div className="mx-auto max-w-xl p-10">
      <ErrorNotice error={isRouteErrorResponse(error) ? error.statusText : error} what="this page" />
    </div>
  );
}

function NotFound() {
  return (
    <div className="mx-auto max-w-xl pt-10">
      <Empty title="This page does not exist">
        <Link to="/" className="text-primary underline">
          Go to the overview
        </Link>
      </Empty>
    </div>
  );
}

// The rich text editor (MDXEditor + CodeMirror) is large: load it only when editing.
const loadEditor = () => import("@/pages/EntryEditPage").then((m) => ({ Component: m.EntryEditPage }));

const router = createBrowserRouter([
  {
    element: <Layout />,
    errorElement: <RouteError />,
    children: [
      { path: "/", element: <Dashboard /> },
      { path: "/search", element: <SearchPage /> },
      { path: "/projects/:projectId", element: <ProjectPage /> },
      { path: "/projects/:projectId/summary", lazy: () => import("@/pages/SummaryPage").then((m) => ({ Component: m.SummaryPage })) },
      { path: "/projects/:projectId/context", element: <ContextPage /> },
      { path: "/projects/:projectId/entries/new", lazy: loadEditor },
      { path: "/projects/:projectId/entries/:entryId", element: <EntryPage /> },
      { path: "/projects/:projectId/entries/:entryId/edit", lazy: loadEditor },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
