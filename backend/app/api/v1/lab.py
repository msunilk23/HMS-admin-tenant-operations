"""
Lab Orders API — manage lab tests ordered by doctors and enter results.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role, require_feature
from app.db.engine import get_session
from app.models.tenant.doctor import Doctor
from app.models.tenant.lab_order import LabOrder, LabResult, LAB_STATUS_TRANSITIONS, can_transition_lab_order
from app.models.tenant.lab_test_master import LabTestMaster
from app.models.tenant.patient import Patient
from app.models.tenant.visit import Visit
from app.schemas.lab import LabOrderCreate, LabOrderRead, LabResultCreate, LabResultRead
from app.websocket.manager import ws_manager
from app.services.audit_service import record_audit

router = APIRouter(dependencies=[Depends(require_feature("lab"))])

ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}
def validate_lab_transition(current_status: str, new_status: str) -> None:
    if new_status not in LAB_STATUS_TRANSITIONS:
        raise HTTPException(status_code=400, detail="Invalid lab order status")
    if not can_transition_lab_order(current_status, new_status):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid lab order transition: {current_status} -> {new_status}",
        )


@router.post("", response_model=LabOrderRead, status_code=status.HTTP_201_CREATED)
async def create_lab_order(
    payload: LabOrderCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("doctor", "hospital_admin")),
):
    """Doctor creates a lab order for a visit."""
    visit = await session.get(Visit, payload.visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    patient = await session.get(Patient, visit.patient_id)
    
    # Validate and enrich test items with metadata from master
    enriched_tests = []
    for test_item in payload.tests:
        test_data = test_item.model_dump()
        
        # If test_id is provided, validate and capture metadata
        if test_item.test_id:
            test_master = await session.get(LabTestMaster, test_item.test_id)
            if not test_master:
                raise HTTPException(status_code=404, detail=f"Lab test not found: {test_item.test_id}")
            if not test_master.is_active:
                raise HTTPException(status_code=400, detail=f"Lab test is inactive: {test_master.code}")
            
            # Snapshot test metadata at order time for audit trail and billing
            test_data["test_id"] = str(test_item.test_id)
            test_data["test_code"] = test_master.code
            test_data["test_name"] = test_master.name
            test_data["category"] = test_master.category
            test_data["sample_type"] = test_master.sample_type
            test_data["price"] = float(test_master.price)  # Server-authoritative pricing
        elif not test_item.test:
            raise HTTPException(status_code=400, detail="Either test_id or test must be provided")
        
        enriched_tests.append(test_data)
    
    order = LabOrder(
        id=uuid.uuid4(),
        visit_id=payload.visit_id,
        uhid=patient.uhid if patient else None,
        tests=enriched_tests,
        status="ordered",
    )
    session.add(order)
    record_audit(
        session,
        current_user=current_user,
        action="CREATE",
        resource_type="lab_order",
        resource_id=order.id,
        patient_id=visit.patient_id,
        visit_id=order.visit_id,
        new_value={"status": order.status, "tests": order.tests},
    )
    await session.commit()
    await session.refresh(order)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "lab:update", {
        "event": "lab_order_created",
        "order_id": str(order.id),
        "visit_id": str(order.visit_id),
    })

    return await _enrich_order(order, session)


@router.get("", response_model=List[LabOrderRead])
async def list_lab_orders(
    status_filter: Optional[str] = Query(None, alias="status"),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("nurse", "doctor", "lab_technician", "receptionist", "hospital_admin")),
):
    stmt = select(LabOrder).order_by(LabOrder.ordered_at.asc())
    if status_filter:
        stmt = stmt.where(LabOrder.status == status_filter)

    # Lab technicians only need to act on orders not yet finalized.
    # LabOrder maintains its own status independent of the OPD visit lifecycle.
    if current_user.get("role") == "lab_technician":
        stmt = stmt.where(LabOrder.status.notin_(["resulted", "result_ready", "verified", "completed", "rejected"]))

    rows = (await session.execute(stmt)).scalars().all()
    return [await _enrich_order(o, session) for o in rows]


@router.patch("/{order_id}/status", response_model=LabOrderRead)
async def update_lab_order_status(
    order_id: uuid.UUID,
    new_status: str,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("nurse", "doctor", "lab_technician", "hospital_admin")),
):
    """Advance a lab order through its independent lifecycle."""
    order = await session.get(LabOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Lab order not found")
    if new_status in ("verified", "completed") and current_user.get("role") not in (
        "lab_technician", "hospital_admin", "super_admin"
    ):
        raise HTTPException(status_code=403, detail="Only lab staff can finalize lab results")
    validate_lab_transition(order.status, new_status)
    old_status = order.status
    now = datetime.now(timezone.utc)
    order.status = new_status
    if new_status == "sample_collected":
        order.sample_collected_at = order.sample_collected_at or now
    elif new_status == "processing":
        order.processing_started_at = order.processing_started_at or now
    elif new_status == "completed":
        order.completed_at = order.completed_at or now
    record_audit(
        session,
        current_user=current_user,
        action="UPDATE",
        resource_type="lab_order",
        resource_id=order.id,
        patient_id=(await session.get(Visit, order.visit_id)).patient_id,
        visit_id=order.visit_id,
        old_value={"status": old_status},
        new_value={"status": new_status},
    )
    await session.commit()
    await session.refresh(order)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "lab:update", {
        "event": "lab_order_status",
        "order_id": str(order.id),
        "status": order.status,
    })
    return await _enrich_order(order, session)


@router.post("/{order_id}/reject", response_model=LabOrderRead)
async def reject_lab_order(
    order_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("lab_technician", "hospital_admin")),
):
    """Reject a sample (contaminated/insufficient) — resets order to 'ordered' for recollection."""
    order = await session.get(LabOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Lab order not found")
    if order.status not in ("sample_pending", "sample_collected", "processing"):
        raise HTTPException(status_code=400, detail="Can only reject after sample collection")
    order.status = "rejected"
    record_audit(
        session,
        current_user=current_user,
        action="UPDATE",
        resource_type="lab_order",
        resource_id=order.id,
        visit_id=order.visit_id,
        old_value={"status": order.status},
        new_value={"status": "rejected"},
        reason="Sample rejected",
    )
    await session.commit()
    await session.refresh(order)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "lab:update", {
        "event": "lab_order_rejected",
        "order_id": str(order.id),
        "visit_id": str(order.visit_id),
    })
    return await _enrich_order(order, session)


@router.post("/{order_id}/results", response_model=LabResultRead, status_code=status.HTTP_201_CREATED)
async def enter_lab_results(
    order_id: uuid.UUID,
    payload: LabResultCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("nurse", "doctor", "lab_technician", "hospital_admin")),
):
    """Enter results for a processing lab order and mark it result-ready."""
    order = await session.get(LabOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Lab order not found")
    if order.status != "processing":
        raise HTTPException(status_code=400, detail="Results can only be entered while processing")

    visit = await session.get(Visit, order.visit_id)
    patient = await session.get(Patient, visit.patient_id) if visit else None
    result = LabResult(
        id=uuid.uuid4(),
        lab_order_id=order_id,
        uhid=patient.uhid if patient else None,
        results=payload.results,
        notes=payload.notes,
        reported_by_user_id=uuid.UUID(current_user["sub"]),
    )
    session.add(result)
    order.status = "result_ready"
    order.result_ready_at = order.result_ready_at or datetime.now(timezone.utc)
    record_audit(
        session,
        current_user=current_user,
        action="CREATE",
        resource_type="lab_result",
        resource_id=result.id,
        visit_id=order.visit_id,
        new_value={"results": payload.results, "notes": payload.notes, "status": order.status},
    )
    await session.commit()
    await session.refresh(result)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "lab:update", {
        "event": "lab_results_entered",
        "order_id": str(order_id),
        "visit_id": str(order.visit_id),
    })
    await ws_manager.broadcast(tenant, "visit:update", {
        "event": "lab_results_ready",
        "visit_id": str(order.visit_id),
    })
    return result


@router.post("/{order_id}/verify", response_model=LabOrderRead)
async def verify_lab_results(
    order_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("lab_technician", "hospital_admin")),
):
    from app.services.lab_billing_service import create_lab_invoice_if_needed
    
    order = await session.get(LabOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Lab order not found")
    validate_lab_transition(order.status, "verified")
    result = (await session.execute(
        select(LabResult).where(LabResult.lab_order_id == order_id)
    )).scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=400, detail="No results available for verification")
    result.verified_by_user_id = uuid.UUID(current_user["sub"])
    result.verified_at = datetime.now(timezone.utc)
    order.verified_at = result.verified_at
    order.status = "verified"
    record_audit(
        session,
        current_user=current_user,
        action="UPDATE",
        resource_type="lab_result",
        resource_id=result.id,
        visit_id=order.visit_id,
        old_value={"status": "result_ready"},
        new_value={"status": "verified", "verified_by_user_id": current_user.get("sub")},
    )
    
    # Create billing invoice for lab charges if needed
    visit = await session.get(Visit, order.visit_id)
    try:
        await create_lab_invoice_if_needed(
            session,
            lab_order_id=order_id,
            visit_id=order.visit_id,
            tests=order.tests or [],
            patient_id=visit.patient_id if visit else None,
            current_user=current_user,
        )
    except Exception as e:
        # Log billing error but don't fail lab verification
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to create lab invoice for order {order_id}: {str(e)}", exc_info=True)
    
    await session.commit()
    await session.refresh(order)
    return await _enrich_order(order, session)


@router.post("/{order_id}/results/upload", response_model=LabResultRead)
async def upload_lab_report(
    order_id: uuid.UUID,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("lab_technician", "hospital_admin")),
):
    """Upload a PDF/image report file and attach it to the existing LabResult."""
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="Only PDF, JPEG, and PNG files are allowed")

    result = (await session.execute(
        select(LabResult).where(LabResult.lab_order_id == order_id)
    )).scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="No result record yet — enter results first")

    # Build meaningful public_id: lab-reports/{UHID}_{PatientName}_{Tests}_{Date}
    order = await session.get(LabOrder, order_id)
    visit = await session.get(Visit, order.visit_id) if order else None
    patient = await session.get(Patient, visit.patient_id) if visit else None

    def _safe(s: str) -> str:
        return s.replace(" ", "_").replace("/", "-")

    uhid = _safe(patient.uhid) if patient else "UNKNOWN"
    patient_name = _safe(f"{patient.first_name}_{patient.last_name}") if patient else "Patient"
    test_names = "-".join(
        _safe(t.get("test", t.get("test_name", "Test")))
        for t in (order.tests or [])
    ) or "Lab"
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Determine resource type and preserve original file extension
    _MIME_TO_EXT = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
    }
    _MIME_TO_FMT = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
    }
    resource_type = "raw" if file.content_type == "application/pdf" else "image"
    file_ext = _MIME_TO_EXT.get(file.content_type or "", "")

    # For raw (PDF) the extension must be part of public_id so Cloudinary preserves it in the URL.
    # For images the extension is managed via the 'format' upload param instead.
    if resource_type == "raw":
        public_id = f"lab-reports/{uhid}_{patient_name}_{test_names}_{date_str}{file_ext}"
    else:
        public_id = f"lab-reports/{uhid}_{patient_name}_{test_names}_{date_str}"

    content = await file.read()

    # Upload to Cloudinary
    from app.core.config import settings
    import cloudinary
    import cloudinary.uploader
    import io

    if not (settings.CLOUDINARY_CLOUD_NAME and settings.CLOUDINARY_API_KEY and settings.CLOUDINARY_API_SECRET):
        raise HTTPException(status_code=503, detail="File storage not configured (Cloudinary credentials missing)")

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )

    # Delete old Cloudinary file if present (best-effort)
    if result.report_url and result.report_url.startswith("https://res.cloudinary.com"):
        try:
            old_public_id = result.report_url.split("/upload/")[-1]
            # Strip version prefix (v1234567890/) if present
            if old_public_id.startswith("v") and "/" in old_public_id:
                old_public_id = old_public_id.split("/", 1)[1]
            # For images (Cloudinary appends extension to URL), strip it for the API call
            if resource_type == "image" and "." in old_public_id.split("/")[-1]:
                old_public_id = old_public_id.rsplit(".", 1)[0]
            cloudinary.uploader.destroy(old_public_id, resource_type=resource_type)
        except Exception:
            pass  # non-critical

    upload_kwargs: dict = dict(
        public_id=public_id,
        resource_type=resource_type,
        overwrite=False,
        type="upload",
    )
    # Force the original image format so Cloudinary doesn't auto-convert to webp/avif
    if resource_type == "image" and file.content_type in _MIME_TO_FMT:
        upload_kwargs["format"] = _MIME_TO_FMT[file.content_type]

    upload_result = cloudinary.uploader.upload(io.BytesIO(content), **upload_kwargs)

    result.report_url = upload_result["secure_url"]
    await session.commit()
    await session.refresh(result)
    return result


@router.get("/{order_id}/results/report")
async def download_lab_report(
    order_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("nurse", "doctor", "lab_technician", "receptionist", "hospital_admin", "super_admin")),
):
    """Return a short-lived signed Cloudinary URL for the lab report."""
    import cloudinary.utils
    from app.core.config import settings

    result = (await session.execute(
        select(LabResult).where(LabResult.lab_order_id == order_id)
    )).scalar_one_or_none()
    if not result or not result.report_url:
        raise HTTPException(status_code=404, detail="No report available for this order")

    # Extract clean public_id from stored URL
    # Handles: s--sig--/v123/lab-reports/file.pdf  |  v123/lab-reports/file.pdf  |  lab-reports/file.pdf
    url_path = result.report_url.split("/upload/")[-1].split("?")[0]
    if url_path.startswith("s--") and "--/" in url_path:
        url_path = url_path.split("--/", 1)[1]
    if url_path.startswith("v") and "/" in url_path and url_path[1:].split("/")[0].isdigit():
        url_path = url_path.split("/", 1)[1]
    public_id = url_path

    resource_type = "raw"

    # Generate a signed delivery URL — bypasses account-level PDF delivery restrictions
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )
    signed_url, _ = cloudinary.utils.cloudinary_url(
        public_id,
        resource_type=resource_type,
        type="upload",
        sign_url=True,
        secure=True,
    )

    return {"url": signed_url}


@router.get("/{order_id}/results", response_model=LabResultRead)
async def get_lab_results(
    order_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("nurse", "doctor", "lab_technician", "receptionist", "hospital_admin")),
):
    result = (await session.execute(
        select(LabResult).where(LabResult.lab_order_id == order_id)
    )).scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="No results yet for this lab order")
    return result


async def _enrich_order(order: LabOrder, session) -> LabOrderRead:
    item = LabOrderRead.model_validate(order)
    # Normalise tests: prescriptions store {"test_name": ...} but the lab schema uses {"test": ...}
    if item.tests:
        normalised = []
        for t in item.tests:
            if isinstance(t, dict) and "test_name" in t and "test" not in t:
                t = {"test": t["test_name"], "notes": t.get("notes")}
            normalised.append(t)
        item.tests = normalised
    visit = await session.get(Visit, order.visit_id)
    if visit:
        patient = await session.get(Patient, visit.patient_id)
        doctor = await session.get(Doctor, visit.doctor_id) if visit.doctor_id else None
        if patient:
            item.patient_name = f"{patient.first_name} {patient.last_name}"
        if doctor:
            item.doctor_name = doctor.full_name
    lab_result = (await session.execute(
        select(LabResult).where(LabResult.lab_order_id == order.id)
    )).scalar_one_or_none()
    if lab_result:
        from app.schemas.lab import LabResultRead
        item.result = LabResultRead.model_validate(lab_result)
    return item

