import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './context/AuthContext.jsx'

import CitizenLayout from './components/CitizenLayout.jsx'
import Home from './pages/citizen/Home.jsx'
import Search from './pages/citizen/Search.jsx'
import Viewer3D from './pages/citizen/Viewer3D.jsx'
import BulkAreaViewer3D from './pages/citizen/BulkAreaViewer3D.jsx'
import PropertyDetail from './pages/citizen/PropertyDetail.jsx'
import GrievanceForm from './pages/citizen/GrievanceForm.jsx'
import GrievanceTrack from './pages/citizen/GrievanceTrack.jsx'
const PublicMap = lazy(() => import('./pages/citizen/PublicMap.jsx'))
import OwnerApproval from './pages/citizen/OwnerApproval.jsx'

import AdminLayout from './components/AdminLayout.jsx'
import AdminLogin from './pages/admin/Login.jsx'
import Signup from './pages/admin/Signup.jsx'
import ForgotPassword from './pages/admin/ForgotPassword.jsx'
import ResetPassword from './pages/admin/ResetPassword.jsx'
import Dashboard from './pages/admin/Dashboard.jsx'
import CreateEntity from './pages/admin/CreateEntity.jsx'
import Ingestion from './pages/admin/Ingestion.jsx'
import ReviewQueue from './pages/admin/ReviewQueue.jsx'
import ReviewDetail from './pages/admin/ReviewDetail.jsx'
import Conflicts from './pages/admin/Conflicts.jsx'
import Grievances from './pages/admin/Grievances.jsx'
import AuditLog from './pages/admin/AuditLog.jsx'
import Underground from './pages/admin/Underground.jsx'
import ChangeDetection from './pages/admin/ChangeDetection.jsx'
import PendingModelRuns from './pages/admin/PendingModelRuns.jsx'
import Notifications from './pages/admin/Notifications.jsx'
import AllRecords from './pages/admin/AllRecords.jsx'
const GisMap = lazy(() => import('./pages/admin/GisMap.jsx'))
import GisMapClassic from './pages/admin/GisMapClassic.jsx'
import ChangeRequests from './pages/admin/ChangeRequests.jsx'
import AdminViewer from './pages/admin/Viewer.jsx'
import UsersAdmin from './pages/admin/UsersAdmin.jsx'
import Settings from './pages/admin/Settings.jsx'

function ProtectedRoute({ children }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/admin/login" replace />
  return children
}

export default function App() {
  return (
    <Suspense fallback={<div className="flex justify-center py-24 text-slate-500 text-sm">Loading…</div>}>
    <Routes>
      <Route path="/" element={<CitizenLayout />}>
        <Route index element={<Home />} />
        <Route path="search" element={<Search />} />
        <Route path="viewer" element={<Viewer3D />} />
        <Route path="map" element={<PublicMap />} />
        <Route path="bulk-viewer" element={<BulkAreaViewer3D />} />
        <Route path="property/:unitId" element={<PropertyDetail />} />
        <Route path="report/:unitId" element={<GrievanceForm />} />
        <Route path="report/building/:buildingId" element={<GrievanceForm />} />
        <Route path="track" element={<GrievanceTrack />} />
        <Route path="owner-approve/:token" element={<OwnerApproval />} />
      </Route>

      <Route path="/admin/login" element={<AdminLogin />} />
      <Route path="/admin/signup" element={<Signup />} />
      <Route path="/admin/forgot-password" element={<ForgotPassword />} />
      <Route path="/admin/reset-password" element={<ResetPassword />} />
      <Route
        path="/admin"
        element={
          <ProtectedRoute>
            <AdminLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="create" element={<CreateEntity />} />
        <Route path="records" element={<AllRecords />} />
        <Route path="gis-map" element={<GisMap />} />
        <Route path="gis-map-classic" element={<GisMapClassic />} />
        <Route path="change-requests" element={<ChangeRequests />} />
        <Route path="viewer" element={<AdminViewer />} />
        <Route path="ingestion" element={<Ingestion />} />
        <Route path="review" element={<ReviewQueue />} />
        <Route path="review/:unitId" element={<ReviewDetail />} />
        <Route path="conflicts" element={<Conflicts />} />
        <Route path="underground" element={<Underground />} />
        <Route path="change-detection" element={<ChangeDetection />} />
        <Route path="pending-model-run" element={<PendingModelRuns />} />
        <Route path="grievances" element={<Grievances />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="audit" element={<AuditLog />} />
        <Route path="users" element={<UsersAdmin />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
    </Suspense>
  )
}
