import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import ProtectedRoute from '@/components/shared/ProtectedRoute'
import RoleGuard from '@/components/shared/RoleGuard'
import FeatureGuard from '@/components/shared/FeatureGuard'
import AppLayout from '@/components/shared/Layout'
import LoginPage from '@/features/auth/LoginPage'
import PatientsPage from '@/features/patients/PatientsPage'
import QueuePage from '@/features/queue/QueuePage'
import TokenDisplayPage from '@/features/queue/TokenDisplayPage'
import NurseVitalsPage from '@/features/nurse/NurseVitalsPage'
import RosterPage from '@/features/nurse/RosterPage'
import ConsultationPage from '@/features/doctor/ConsultationPage'
import PrescriptionPage from '@/features/doctor/PrescriptionPage'
import LabResultsPage from '@/features/doctor/LabResultsPage'
import BillingPage from '@/features/billing/BillingPage'
import PosScreen from '@/features/billing/PosScreen'
import DoctorsAdminPage from '@/features/admin/DoctorsAdminPage'
import DoctorSchedulesPage from '@/features/admin/DoctorSchedulesPage'
import UsersAdminPage from '@/features/admin/UsersAdminPage'
import BrandingPage from '@/features/admin/BrandingPage'
import AppointmentsPage from '@/features/appointments/AppointmentsPage'
import RegisterVisitPage from '@/features/reception/RegisterVisitPage'
import ChangePasswordPage from '@/features/auth/ChangePasswordPage'
import PharmacyPage from '@/features/pharmacy/PharmacyPage'
import PurchaseOrderPage from '@/features/pharmacy/PurchaseOrderPage'
import GoodsReceiptPage from '@/features/pharmacy/GoodsReceiptPage'
import PatientReturnsPage from '@/features/pharmacy/PatientReturnsPage'
import SupplierReturnsPage from '@/features/pharmacy/SupplierReturnsPage'
import QuarantinePage from '@/features/pharmacy/QuarantinePage'
import P32OperationsPage from '@/features/pharmacy/P32OperationsPage'
import InventoryCountPage from '@/features/pharmacy/InventoryCountPage'
import PharmacyDashboardPage from '@/features/pharmacy/PharmacyDashboardPage'
import LabPage from '@/features/lab/LabPage'
import AdminDashboard from '@/features/admin/AdminDashboard'
import TenantsPage from '@/features/super_admin/TenantsPage'
import RequisitionsPage from '@/features/requisitions/RequisitionsPage'
import PharmacyAdminPage from '@/features/admin/PharmacyAdminPage'

import { useAuthStore } from '@/features/auth/authStore'
import TenantBranding from '@/components/shared/TenantBranding'
import PermissionGuard from '@/components/shared/PermissionGuard'
import { P34_PERMISSIONS } from '@/services/pharmacyDashboardService'

const ADMIN = ['hospital_admin']
const DOCTOR = ['doctor', ...ADMIN]
const NURSE = ['nurse', ...ADMIN]
const LAB = ['lab_technician', ...ADMIN]
const PHARMACY = ['pharmacist', ...ADMIN]
const BILLING = ['billing_officer', ...ADMIN]
const RECEPTION = ['receptionist', ...ADMIN]
const CLINICAL = ['receptionist', 'nurse', 'doctor', ...ADMIN]
const ALL_STAFF = ['hospital_admin', 'receptionist', 'nurse', 'doctor', 'lab_technician', 'pharmacist', 'billing_officer', 'store_manager']

function Dashboard() {
  const role = useAuthStore((s) => s.user?.role ?? '')
  if (role === 'doctor') return <Navigate to="/doctor/consultation" replace />
  if (role === 'nurse') return <Navigate to="/nurse/vitals" replace />
  if (role === 'pharmacist') return <Navigate to="/pharmacy" replace />
  if (role === 'lab_technician') return <Navigate to="/lab" replace />
  if (role === 'receptionist') return <Navigate to="/patients" replace />
  if (role === 'hospital_admin') return <AdminDashboard />
  if (role === 'store_manager') return <Navigate to="/indent" replace />
  if (role === 'super_admin') return <Navigate to="/super/hospitals" replace />
  return <div className="p-6"><h1 className="text-2xl font-semibold">Command Center</h1></div>
}

function SessionExpiredModal() {
  const { sessionExpired, logout } = useAuthStore()
  const navigate = useNavigate()
  if (!sessionExpired) return null
  const handleReLogin = () => {
    logout()
    navigate('/login', { replace: true })
  }
  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl max-w-sm w-full mx-4 p-8 text-center space-y-5">
        <div className="flex justify-center">
          <div className="w-16 h-16 bg-amber-100 rounded-full flex items-center justify-center">
            <svg className="w-8 h-8 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            </svg>
          </div>
        </div>
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Session Expired</h2>
          <p className="text-sm text-gray-500 mt-1.5">
            Your session is no longer valid — the server security key may have been rotated. Please log in again to continue.
          </p>
        </div>
        <button
          onClick={handleReLogin}
          className="w-full bg-primary text-white py-2.5 rounded-lg font-medium text-sm hover:bg-primary/90 transition-colors"
        >
          Log In Again
        </button>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <TenantBranding />
      <SessionExpiredModal />
      <Routes>
        {/* Public routes */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/display/:tenantSchema/:displayToken" element={<TokenDisplayPage />} />
        <Route path="/pos/:tenantSchema" element={<PosScreen />} />

        {/* Protected routes — all inside the app shell */}
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/patients" element={<RoleGuard allowed={CLINICAL}><PatientsPage /></RoleGuard>} />
            <Route path="/register-visit" element={<RoleGuard allowed={RECEPTION}><RegisterVisitPage /></RoleGuard>} />
            <Route path="/appointments" element={<FeatureGuard feature="appointments"><RoleGuard allowed={[...RECEPTION, 'nurse', 'doctor']}><AppointmentsPage /></RoleGuard></FeatureGuard>} />
            <Route path="/queue" element={<FeatureGuard feature="opd_queue"><RoleGuard allowed={[...RECEPTION, 'nurse']}><QueuePage /></RoleGuard></FeatureGuard>} />
            <Route path="/nurse/vitals" element={<FeatureGuard feature="vitals"><RoleGuard allowed={NURSE}><NurseVitalsPage /></RoleGuard></FeatureGuard>} />
            <Route path="/nurse/roster" element={<FeatureGuard feature="nurse_roster"><RoleGuard allowed={NURSE}><RosterPage /></RoleGuard></FeatureGuard>} />
            <Route path="/doctor/consultation" element={<RoleGuard allowed={DOCTOR}><ConsultationPage /></RoleGuard>} />
            <Route path="/doctor/consultation/:visitId" element={<RoleGuard allowed={DOCTOR}><ConsultationPage /></RoleGuard>} />
            <Route path="/doctor/prescription/:visitId" element={<RoleGuard allowed={DOCTOR}><PrescriptionPage /></RoleGuard>} />
            <Route path="/doctor/lab-results" element={<RoleGuard allowed={DOCTOR}><LabResultsPage /></RoleGuard>} />
            <Route path="/lab" element={<FeatureGuard feature="lab"><RoleGuard allowed={LAB}><LabPage /></RoleGuard></FeatureGuard>} />
            <Route path="/pharmacy" element={<FeatureGuard feature="pharmacy"><RoleGuard allowed={PHARMACY}><PharmacyPage /></RoleGuard></FeatureGuard>} />
            <Route path="/pharmacy/dashboard" element={<FeatureGuard feature="pharmacy"><PermissionGuard permission={P34_PERMISSIONS.dashboard}><PharmacyDashboardPage /></PermissionGuard></FeatureGuard>} />
            <Route path="/pharmacy/patient-returns" element={<FeatureGuard feature="pharmacy"><RoleGuard allowed={PHARMACY}><PatientReturnsPage /></RoleGuard></FeatureGuard>} />
            <Route path="/pharmacy/supplier-returns" element={<FeatureGuard feature="pharmacy"><RoleGuard allowed={PHARMACY}><SupplierReturnsPage /></RoleGuard></FeatureGuard>} />
            <Route path="/pharmacy/quarantine" element={<FeatureGuard feature="pharmacy"><RoleGuard allowed={['pharmacist', 'store_manager', 'hospital_admin']}><QuarantinePage /></RoleGuard></FeatureGuard>} />
            <Route path="/pharmacy/operations" element={<FeatureGuard feature="pharmacy"><RoleGuard allowed={['pharmacist', 'store_manager', 'hospital_admin']}><P32OperationsPage /></RoleGuard></FeatureGuard>} />
            <Route path="/pharmacy/inventory-counts" element={<FeatureGuard feature="pharmacy"><RoleGuard allowed={['pharmacist', 'store_manager', 'hospital_admin', 'auditor']}><InventoryCountPage /></RoleGuard></FeatureGuard>} />
            <Route path="/admin/pharmacy/purchase-orders" element={<RoleGuard allowed={['hospital_admin', 'store_manager']}><PurchaseOrderPage /></RoleGuard>} />
            <Route path="/admin/pharmacy/goods-receipts" element={<RoleGuard allowed={['hospital_admin', 'store_manager']}><GoodsReceiptPage /></RoleGuard>} />
            <Route path="/billing" element={<FeatureGuard feature="billing"><RoleGuard allowed={BILLING}><BillingPage /></RoleGuard></FeatureGuard>} />
            <Route path="/indent" element={<RoleGuard allowed={ALL_STAFF}><RequisitionsPage /></RoleGuard>} />
            <Route path="/admin/doctors" element={<RoleGuard allowed={ADMIN}><DoctorsAdminPage /></RoleGuard>} />
            <Route path="/admin/doctors/schedules" element={<RoleGuard allowed={ADMIN}><DoctorSchedulesPage /></RoleGuard>} />
            <Route path="/admin/users" element={<RoleGuard allowed={['hospital_admin']}><UsersAdminPage /></RoleGuard>} />
            <Route path="/admin/branding" element={<RoleGuard allowed={ADMIN}><BrandingPage /></RoleGuard>} />
            <Route path="/admin/pharmacy" element={<RoleGuard allowed={ADMIN}><PharmacyAdminPage /></RoleGuard>} />
            <Route path="/super/hospitals" element={<RoleGuard allowed={['super_admin']}><TenantsPage /></RoleGuard>} />
            <Route path="/change-password" element={<ChangePasswordPage />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
