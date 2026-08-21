from fastapi import APIRouter, Depends

from app.api.v1.admin import router as admin_router
from app.api.v1.appointments import router as appointments_router
from app.api.v1.auth import router as auth_router
from app.api.v1.billing import router as billing_router, webhook_router as billing_webhook_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.consultations import router as consultations_router
from app.api.v1.clinical_alerts import router as clinical_alerts_router
from app.api.v1.departments import router as departments_router
from app.api.v1.doctors import router as doctors_router
from app.api.v1.lab import router as lab_router
from app.api.v1.nurse_departments import router as nurse_departments_router
from app.api.v1.nurse_roster import router as nurse_roster_router
from app.api.v1.patients import router as patients_router
from app.api.v1.pharmacy import router as pharmacy_router
from app.api.v1.prescriptions import router as prescriptions_router
from app.api.v1.queue import router as queue_router
from app.api.v1.requisitions import router as requisitions_router
from app.api.v1.super_admin import router as super_admin_router
from app.api.v1.tenants import router as tenants_router
from app.api.v1.users import router as users_router
from app.api.v1.visits import router as visits_router
from app.api.v1.vitals import router as vitals_router
from app.api.v1.master_data import router as master_data_router
from app.core.dependencies import require_tenant_user

api_router = APIRouter()

# Public / cross-tenant routes — no tenant guard
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(super_admin_router, prefix="/super", tags=["super-admin"])

# Tenant-scoped routes — super_admin is explicitly blocked at the backend
_tenant_guard = {"dependencies": [Depends(require_tenant_user)]}

api_router.include_router(admin_router, prefix="/admin", tags=["admin"], **_tenant_guard)
api_router.include_router(tenants_router, prefix="/tenants", tags=["tenants"], **_tenant_guard)
api_router.include_router(users_router, prefix="/users", tags=["users"], **_tenant_guard)
api_router.include_router(patients_router, prefix="/patients", tags=["patients"], **_tenant_guard)
api_router.include_router(departments_router, prefix="/departments", tags=["departments"], **_tenant_guard)
api_router.include_router(doctors_router, prefix="/doctors", tags=["doctors"], **_tenant_guard)
api_router.include_router(appointments_router, prefix="/appointments", tags=["appointments"], **_tenant_guard)
api_router.include_router(queue_router, prefix="/queue", tags=["queue"], **_tenant_guard)
api_router.include_router(visits_router, prefix="/visits", tags=["visits"], **_tenant_guard)
api_router.include_router(vitals_router, prefix="/vitals", tags=["vitals"], **_tenant_guard)
api_router.include_router(master_data_router, prefix="/master-data", tags=["master-data"], **_tenant_guard)
api_router.include_router(consultations_router, prefix="/consultations", tags=["consultations"], **_tenant_guard)
api_router.include_router(clinical_alerts_router, prefix="/clinical-alerts", tags=["clinical-alerts"], **_tenant_guard)
api_router.include_router(prescriptions_router, prefix="/prescriptions", tags=["prescriptions"], **_tenant_guard)
api_router.include_router(billing_router, prefix="/billing", tags=["billing"], **_tenant_guard)
api_router.include_router(billing_webhook_router, prefix="/billing", tags=["billing"])  # no guard — Razorpay webhook
api_router.include_router(feedback_router, prefix="/feedback", tags=["feedback"], **_tenant_guard)
api_router.include_router(nurse_departments_router, prefix="/nurse-departments", tags=["nurse-departments"], **_tenant_guard)
api_router.include_router(nurse_roster_router, prefix="/nurse-roster", tags=["nurse-roster"], **_tenant_guard)
api_router.include_router(pharmacy_router, prefix="/pharmacy", tags=["pharmacy"], **_tenant_guard)
api_router.include_router(lab_router, prefix="/lab", tags=["lab"], **_tenant_guard)
api_router.include_router(requisitions_router, prefix="/indents", tags=["indents"], **_tenant_guard)
