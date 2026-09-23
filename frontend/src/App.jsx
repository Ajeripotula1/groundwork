import { Routes, Route } from 'react-router-dom'
import { SignIn, SignUp } from '@clerk/clerk-react'
import { ProtectedRoute } from './components/ProtectedRoute'
import { AppLayout } from './components/AppLayout'
import { HomePage } from './pages/HomePage'
import { JobListPage } from './pages/JobListPage'
import { JobDetailPage } from './pages/JobDetailPage'
import { ProfilePage } from './pages/ProfilePage'
import { NotFoundPage } from './pages/NotFoundPage'

function App() {
  return (
    <Routes>
      {/* Clerk Sign-in and Sign-out routes */}
      <Route
        path="/sign-in/*"
        element={
          <div className="flex min-h-screen items-center justify-center">
            <SignIn />
          </div>
        }
      />
      <Route
        path="/sign-up/*"
        element={
          <div className="flex min-h-screen items-center justify-center">
            <SignUp />
          </div>
        }
      />
      {/* Pathless App Layout Wrapper for all pages */}
      <Route element={<AppLayout />}>
        <Route index element={<HomePage />} />
        <Route path="jobs" element={<JobListPage />} />
        <Route path="jobs/:jobId" element={<JobDetailPage />} />
        <Route
          path="profile"
          element={
            <ProtectedRoute>
              <ProfilePage />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export default App