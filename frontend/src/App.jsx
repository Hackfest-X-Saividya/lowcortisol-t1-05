import { lazy, Suspense, useEffect } from "react";
import { match, navigate, usePath } from "./lib/router.js";
import Landing from "./pages/Landing.jsx";

const Login = lazy(() => import("./pages/staff/Login.jsx"));
const Cases = lazy(() => import("./pages/staff/Cases.jsx"));
const CaseFile = lazy(() => import("./pages/staff/CaseFile.jsx"));
const SessionDesk = lazy(() => import("./pages/staff/SessionDesk.jsx"));
const Admin = lazy(() => import("./pages/staff/Admin.jsx"));
const Witness = lazy(() => import("./pages/witness/Witness.jsx"));

const ROUTES = [
  ["/app", Login],
  ["/app/cases", Cases],
  ["/app/cases/:id", CaseFile],
  ["/app/sessions/:id", SessionDesk],
  ["/app/admin", Admin],
  ["/witness/:sid", Witness],
];

function NotFound() {
  useEffect(() => navigate("/", { replace: true }), []);
  return null;
}

export default function App() {
  const path = usePath();
  if (path === "/" || path === "") return <Landing />;
  for (const [pattern, Page] of ROUTES) {
    const params = match(pattern, path);
    if (params)
      return (
        <Suspense fallback={<div className="loading-wall" />}>
          <Page key={path} {...params} />
        </Suspense>
      );
  }
  return <NotFound />;
}
