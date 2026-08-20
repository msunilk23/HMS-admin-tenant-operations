"""Admin Stats API — single endpoint returning all KPIs for the hospital_admin dashboard."""
from datetime import date, datetime, timezone
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.db.engine import get_session, tenant_schema_var
from app.models.tenant.appointment import Appointment
from app.models.tenant.department import Department
from app.models.tenant.lab_order import LabOrder
from app.models.tenant.patient import Patient
from app.models.tenant.pharmacy_queue import PharmacyQueue
from app.models.tenant.invoice import Invoice
from app.models.tenant.visit import Visit
from app.models.public.user import User

router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────────

class StaffRole(BaseModel):
    role: str
    count: int


class DeptStat(BaseModel):
    name: str
    total: int
    completed: int       # visits with status='closed'
    in_progress: int     # all other non-closed visits


class AdminStats(BaseModel):
    # Patients
    total_patients: int
    new_patients_today: int

    # Staff
    total_staff: int
    staff_by_role: List[StaffRole]

    # OPD today
    visits_today: int
    visits_completed_today: int
    visits_in_progress_today: int

    # Appointments today
    appointments_today: int
    appointments_completed_today: int
    appointments_cancelled_today: int

    # Department breakdown (all-time)
    departments: List[DeptStat]

    # Pharmacy (all-time)
    pharmacy_dispensed: int
    pharmacy_pending: int
    pharmacy_total: int

    # Lab (all-time)
    lab_resulted: int
    lab_rejected: int
    lab_pending: int
    lab_total: int

    # Billing / Revenue
    revenue_today: float
    revenue_total: float
    invoices_paid_today: int
    invoices_draft: int


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=AdminStats)
async def get_admin_stats(
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("hospital_admin", "super_admin")),
):
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)

    # ── Patients ──────────────────────────────────────────────────────────
    total_patients = (await session.execute(
        select(func.count()).select_from(Patient).where(Patient.is_active == True)  # noqa: E712
    )).scalar() or 0

    new_patients_today = (await session.execute(
        select(func.count()).select_from(Patient)
        .where(Patient.created_at >= today_start)
    )).scalar() or 0

    # ── Staff (public schema, filtered by current tenant) ─────────────────
    schema = tenant_schema_var.get()
    staff_rows = (await session.execute(
        select(User.role, func.count().label("cnt"))
        .where(User.tenant_name == schema, User.is_active == True)  # noqa: E712
        .group_by(User.role)
        .order_by(User.role)
    )).all()
    staff_by_role = [StaffRole(role=r, count=c) for r, c in staff_rows]
    total_staff = sum(s.count for s in staff_by_role)

    # ── Visits today ──────────────────────────────────────────────────────
    visits_today = (await session.execute(
        select(func.count()).select_from(Visit)
        .where(Visit.created_at >= today_start)
    )).scalar() or 0

    visits_completed_today = (await session.execute(
        select(func.count()).select_from(Visit)
        .where(Visit.created_at >= today_start, Visit.status == VisitStatus.CLOSED.value)
    )).scalar() or 0

    visits_in_progress_today = visits_today - visits_completed_today

    # ── Appointments today ────────────────────────────────────────────────
    appointments_today = (await session.execute(
        select(func.count()).select_from(Appointment)
        .where(Appointment.slot_time >= today_start)
    )).scalar() or 0

    appointments_completed_today = (await session.execute(
        select(func.count()).select_from(Appointment)
        .where(Appointment.slot_time >= today_start, Appointment.status == "completed")
    )).scalar() or 0

    appointments_cancelled_today = (await session.execute(
        select(func.count()).select_from(Appointment)
        .where(Appointment.slot_time >= today_start, Appointment.status == "cancelled")
    )).scalar() or 0

    # ── Departments (all-time visits) ─────────────────────────────────────
    dept_rows = (await session.execute(
        select(
            Department.name,
            func.count(Visit.id).label("total"),
            func.count(
                case((Visit.status == VisitStatus.CLOSED.value, Visit.id))
            ).label("completed"),
        )
        .outerjoin(Visit, Visit.department_id == Department.id)
        .where(Department.is_active == True)  # noqa: E712
        .group_by(Department.id, Department.name)
        .order_by(Department.name)
    )).all()

    departments = [
        DeptStat(
            name=name,
            total=total or 0,
            completed=completed or 0,
            in_progress=(total or 0) - (completed or 0),
        )
        for name, total, completed in dept_rows
    ]

    # ── Pharmacy (all-time) ───────────────────────────────────────────────
    pharmacy_rows = (await session.execute(
        select(PharmacyQueue.status, func.count().label("cnt"))
        .group_by(PharmacyQueue.status)
    )).all()
    pharmacy_by_status: dict[str, int] = {r: c for r, c in pharmacy_rows}
    pharmacy_dispensed = pharmacy_by_status.get("dispensed", 0)
    pharmacy_total = sum(pharmacy_by_status.values())
    pharmacy_pending = pharmacy_total - pharmacy_dispensed

    # ── Lab (all-time) ────────────────────────────────────────────────────
    lab_rows = (await session.execute(
        select(LabOrder.status, func.count().label("cnt"))
        .group_by(LabOrder.status)
    )).all()
    lab_by_status: dict[str, int] = {r: c for r, c in lab_rows}
    lab_resulted = lab_by_status.get("resulted", 0)
    lab_rejected = lab_by_status.get("rejected", 0)
    lab_total = sum(lab_by_status.values())
    lab_pending = lab_total - lab_resulted - lab_rejected

    # ── Billing / Revenue ─────────────────────────────────────────────────
    revenue_today = float((await session.execute(
        select(func.coalesce(func.sum(Invoice.total), 0))
        .where(Invoice.status == "paid", Invoice.created_at >= today_start)
    )).scalar() or 0)

    revenue_total = float((await session.execute(
        select(func.coalesce(func.sum(Invoice.total), 0))
        .where(Invoice.status == "paid")
    )).scalar() or 0)

    invoices_paid_today = (await session.execute(
        select(func.count()).select_from(Invoice)
        .where(Invoice.status == "paid", Invoice.created_at >= today_start)
    )).scalar() or 0

    invoices_draft = (await session.execute(
        select(func.count()).select_from(Invoice)
        .where(Invoice.status == "draft")
    )).scalar() or 0

    return AdminStats(
        total_patients=total_patients,
        new_patients_today=new_patients_today,
        total_staff=total_staff,
        staff_by_role=staff_by_role,
        visits_today=visits_today,
        visits_completed_today=visits_completed_today,
        visits_in_progress_today=visits_in_progress_today,
        appointments_today=appointments_today,
        appointments_completed_today=appointments_completed_today,
        appointments_cancelled_today=appointments_cancelled_today,
        departments=departments,
        pharmacy_dispensed=pharmacy_dispensed,
        pharmacy_pending=pharmacy_pending,
        pharmacy_total=pharmacy_total,
        lab_resulted=lab_resulted,
        lab_rejected=lab_rejected,
        lab_pending=lab_pending,
        lab_total=lab_total,
        revenue_today=revenue_today,
        revenue_total=revenue_total,
        invoices_paid_today=invoices_paid_today,
        invoices_draft=invoices_draft,
    )
