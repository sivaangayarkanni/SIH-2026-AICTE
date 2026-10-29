import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { ReactNode, Suspense, lazy } from 'react'
import { useAuth } from './lib/auth'
import { Layout } from './components/Layout'
import Login from './pages/Login'
import AuthCallback from './pages/AuthCallback'
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Applications = lazy(() => import('./pages/Applications'))
const NewApplication = lazy(() => import('./pages/NewApplication'))
const ApplicationDetail = lazy(() => import('./pages/ApplicationDetail'))
const Readiness = lazy(() => import('./pages/Readiness'))
const Queue = lazy(() => import('./pages/Queue'))
const Overrides = lazy(() => import('./pages/Overrides'))
const Collusion = lazy(() => import('./pages/Collusion'))
const Security = lazy(() => import('./pages/Security'))
const Audit = lazy(() => import('./pages/Audit'))
const Rules = lazy(() => import('./pages/Rules'))
const Admin = lazy(() => import('./pages/Admin'))
const Settings = lazy(() => import('./pages/Settings'))
const Notifications = lazy(() => import('./pages/Notifications'))
const HowItWorks = lazy(() => import('./pages/HowItWorks'))
import { Logo } from './components/Logo'

function Guard({ children, roles }: { children: ReactNode; roles?: string[] }) {
  const { user, loading } = useAuth(); const loc = useLocation()
  if (loading) return <div className="flex h-full items-center justify-center"><div className="animate-pulse"><Logo size={48} /></div></div>
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname }} replace />
  if (roles && !roles.includes(user.role)) return <Layout><div className="card card-pad text-center"><h2 className="font-display text-xl font-bold">Not available for your role</h2><p className="mt-1 text-sm text-muted">Role-based access control (RBAC) restricts this page to: {roles.join(', ')}.</p></div></Layout>
  return <Layout><Suspense fallback={<div className="space-y-3"><div className="skeleton h-8 w-64" /><div className="skeleton h-40 w-full" /></div>}>{children}</Suspense></Layout>
}
const STAFF = ['officer', 'senior_officer', 'admin']

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route path="/" element={<Guard><Dashboard /></Guard>} />
      <Route path="/applications" element={<Guard><Applications /></Guard>} />
      <Route path="/applications/new" element={<Guard roles={['college']}><NewApplication /></Guard>} />
      <Route path="/applications/:id" element={<Guard><ApplicationDetail /></Guard>} />
      <Route path="/readiness" element={<Guard><Readiness /></Guard>} />
      <Route path="/queue" element={<Guard roles={STAFF}><Queue /></Guard>} />
      <Route path="/overrides" element={<Guard roles={STAFF}><Overrides /></Guard>} />
      <Route path="/collusion" element={<Guard roles={STAFF}><Collusion /></Guard>} />
      <Route path="/security" element={<Guard><Security /></Guard>} />
      <Route path="/audit" element={<Guard roles={STAFF}><Audit /></Guard>} />
      <Route path="/rules" element={<Guard><Rules /></Guard>} />
      <Route path="/admin" element={<Guard roles={STAFF}><Admin /></Guard>} />
      <Route path="/notifications" element={<Guard><Notifications /></Guard>} />
      <Route path="/settings" element={<Guard><Settings /></Guard>} />
      <Route path="/how-it-works" element={<Guard><HowItWorks /></Guard>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
