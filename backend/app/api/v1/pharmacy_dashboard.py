from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_facility_id, get_tenant_id_from_token
from app.core.dependencies import get_current_user, require_feature, require_permission
from app.db.engine import get_session
from app.models.public.permission import Permission, RolePermission
from app.models.tenant.p31_p34 import (
    PharmacyAlert,
    PharmacyAlertAcknowledgement,
    PharmacyAlertConfiguration,
    PharmacyDashboardOperation,
)
from app.schemas.pharmacy_dashboard import (
    AlertAcknowledgeRequest,
    AlertConfigurationRead,
    AlertConfigurationWrite,
    PharmacyAlertList,
    PharmacyAlertRead,
    PharmacyCapabilityRead,
    PharmacyDashboardRead,
    PharmacyReportRead,
)
from app.services.audit_service import record_audit
from app.services.pharmacy_dashboard_service import (
    REPORT_NAMES,
    dashboard_cards,
    effective_configuration,
    list_alerts,
    recalculate_alerts,
    report_rows,
    validate_location,
)

router = APIRouter(dependencies=[Depends(require_feature("pharmacy"))])


def _request_hash(payload: Any) -> str:
    encoded = json.dumps(jsonable_encoder(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _replay(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    scope_resource: str,
    idempotency_key: str,
    request_hash: str,
) -> dict[str, Any] | None:
    operation = await session.scalar(select(PharmacyDashboardOperation).where(
        PharmacyDashboardOperation.tenant_id == tenant_id,
        PharmacyDashboardOperation.user_id == user_id,
        PharmacyDashboardOperation.action == action,
        PharmacyDashboardOperation.scope_resource == scope_resource,
        PharmacyDashboardOperation.idempotency_key == idempotency_key,
    ))
    if operation is None:
        return None
    if operation.request_hash != request_hash:
        raise HTTPException(status_code=409, detail="Idempotency key was already used with a different payload")
    return operation.response_payload


def _operation(*, tenant_id: uuid.UUID, facility_id: uuid.UUID, user_id: uuid.UUID, action: str, scope_resource: str, idempotency_key: str, request_hash: str, response_payload: Any) -> PharmacyDashboardOperation:
    return PharmacyDashboardOperation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        user_id=user_id,
        action=action,
        scope_resource=scope_resource,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        response_payload=jsonable_encoder(response_payload),
    )


@router.get("/capabilities", response_model=PharmacyCapabilityRead)
async def capabilities(
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    permissions = (await session.execute(select(Permission.code).join(
        RolePermission, RolePermission.permission_id == Permission.id
    ).where(
        RolePermission.role == current_user.get("role"),
        Permission.is_active.is_(True),
        Permission.code.in_((
            "PHARMACY_DASHBOARD_VIEW", "PHARMACY_REPORT_VIEW", "PHARMACY_REPORT_EXPORT",
            "PHARMACY_ALERT_VIEW", "PHARMACY_ALERT_ACKNOWLEDGE", "PHARMACY_ALERT_CONFIGURE",
            "PHARMACY_AUDIT_VIEW",
        )),
    ).order_by(Permission.code))).scalars().all()
    return {"permissions": list(permissions)}


@router.get("", response_model=PharmacyDashboardRead)
async def dashboard(
    pharmacy_location_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_DASHBOARD_VIEW")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    return await dashboard_cards(
        session,
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=pharmacy_location_id,
        timezone_name=current_user.get("timezone"),
        financial_data_visible=current_user.get("role") != "pharmacist",
    )


@router.get("/reports", response_model=list[str])
async def report_catalogue(current_user: dict = Depends(require_permission("PHARMACY_REPORT_VIEW"))):
    excluded = {"sales-payments", "inventory-valuation", "audit"} if current_user.get("role") == "pharmacist" else set()
    return [name for name in REPORT_NAMES if name not in excluded]


@router.get("/reports/{report}", response_model=PharmacyReportRead)
async def report(
    report: str,
    start_date: date | None = None,
    end_date: date | None = None,
    pharmacy_location_id: uuid.UUID | None = None,
    medicine_id: uuid.UUID | None = None,
    batch_number: str | None = Query(None, max_length=100),
    supplier_id: uuid.UUID | None = None,
    report_status: str | None = Query(None, alias="status", max_length=50),
    alert_type: str | None = Query(None, max_length=50),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_REPORT_VIEW")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    today = datetime.now(timezone.utc).date()
    if current_user.get("role") == "pharmacist" and report in {"sales-payments", "inventory-valuation", "audit"}:
        raise HTTPException(status_code=403, detail="Financial and audit reports require additional permission")
    if report == "audit":
        await require_permission(session, current_user.get("sub"), "PHARMACY_AUDIT_VIEW")
    return await report_rows(
        session,
        report=report,
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=pharmacy_location_id,
        timezone_name=current_user.get("timezone"),
        start_date=start_date or today - date.resolution * 30,
        end_date=end_date or today,
        page=page,
        page_size=page_size,
        medicine_id=medicine_id, batch_number=batch_number, supplier_id=supplier_id,
        status=report_status, alert_type=alert_type,
    )


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(jsonable_encoder(value), sort_keys=True)
    text = str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


@router.get("/reports/{report}/export")
async def export_report(
    report: str,
    start_date: date | None = None,
    end_date: date | None = None,
    pharmacy_location_id: uuid.UUID | None = None,
    medicine_id: uuid.UUID | None = None,
    batch_number: str | None = Query(None, max_length=100),
    supplier_id: uuid.UUID | None = None,
    report_status: str | None = Query(None, alias="status", max_length=50),
    alert_type: str | None = Query(None, max_length=50),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_REPORT_EXPORT")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    today = datetime.now(timezone.utc).date()
    result = await report_rows(
        session, report=report, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=pharmacy_location_id, timezone_name=current_user.get("timezone"),
        start_date=start_date or today - date.resolution * 30, end_date=end_date or today,
        page=1, page_size=10_001, medicine_id=medicine_id, batch_number=batch_number,
        supplier_id=supplier_id, status=report_status, alert_type=alert_type,
    )
    if result["total"] > 10_000:
        raise HTTPException(status_code=422, detail="Export exceeds 10,000 rows; narrow the report filters")
    output = io.StringIO(newline="")
    output.write(f"# report,{_csv_value(report)}\n")
    output.write(f"# tenant,{_csv_value(tenant_id)}\n# facility,{_csv_value(facility_id)}\n")
    output.write(f"# pharmacy_location,{_csv_value(pharmacy_location_id)}\n# timezone,{_csv_value(result['metadata']['timezone'])}\n")
    output.write(f"# currency,INR\n# generated_at,{_csv_value(result['metadata']['generated_at'])}\n# generated_by,{_csv_value(current_user.get('sub'))}\n")
    items = result["items"]
    if items:
        writer = csv.DictWriter(output, fieldnames=list(items[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows({key: _csv_value(value) for key, value in item.items()} for item in items)
    record_audit(
        session, current_user=current_user, action="PHARMACY_REPORT_EXPORTED",
        resource_type="pharmacy_report", resource_id=report,
        new_value={"report": report, "rows": len(items), "filters": result["filters"], "facility_id": str(facility_id)},
    )
    await session.commit()
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="pharmacy-{report}.csv"'})


@router.get("/alerts", response_model=PharmacyAlertList)
async def alerts(
    pharmacy_location_id: uuid.UUID | None = None,
    alert_status: str | None = Query(None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_permission("PHARMACY_ALERT_VIEW")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    return await list_alerts(session, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=pharmacy_location_id, status=alert_status, page=page, page_size=page_size)


@router.post("/alerts/recalculate", response_model=dict[str, int])
async def recalculate_pharmacy_alerts(
    pharmacy_location_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_ALERT_CONFIGURE")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    result = await recalculate_alerts(
        session, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=pharmacy_location_id, timezone_name=current_user.get("timezone"),
    )
    record_audit(
        session, current_user=current_user, action="PHARMACY_ALERTS_RECALCULATED",
        resource_type="pharmacy_alert", resource_id=str(pharmacy_location_id or facility_id),
        new_value={**result, "facility_id": str(facility_id), "pharmacy_location_id": str(pharmacy_location_id) if pharmacy_location_id else None},
    )
    await session.commit()
    return result


@router.post("/alerts/{alert_id}/acknowledge", response_model=PharmacyAlertRead)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    payload: AlertAcknowledgeRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_ALERT_ACKNOWLEDGE")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    actor = uuid.UUID(current_user["sub"])
    digest = _request_hash(payload)
    replay = await _replay(session, tenant_id=tenant_id, user_id=actor, action="ACKNOWLEDGE", scope_resource=str(alert_id), idempotency_key=idempotency_key, request_hash=digest)
    if replay:
        return replay
    alert = await session.scalar(select(PharmacyAlert).where(
        PharmacyAlert.id == alert_id, PharmacyAlert.tenant_id == tenant_id,
        PharmacyAlert.facility_id == facility_id,
    ).with_for_update())
    if alert is None:
        raise HTTPException(status_code=404, detail="Pharmacy alert not found")
    replay = await _replay(session, tenant_id=tenant_id, user_id=actor, action="ACKNOWLEDGE", scope_resource=str(alert_id), idempotency_key=idempotency_key, request_hash=digest)
    if replay:
        return replay
    if alert.status != "OPEN":
        raise HTTPException(status_code=409, detail="Only an open alert can be acknowledged")
    alert.status = "ACKNOWLEDGED"
    acknowledgement = PharmacyAlertAcknowledgement(
        alert_id=alert.id, tenant_id=tenant_id, facility_id=facility_id,
        acknowledged_by=actor, note=payload.note.strip(),
    )
    session.add(acknowledgement)
    await session.flush()
    response = PharmacyAlertRead.model_validate(alert)
    session.add(_operation(tenant_id=tenant_id, facility_id=facility_id, user_id=actor, action="ACKNOWLEDGE", scope_resource=str(alert_id), idempotency_key=idempotency_key, request_hash=digest, response_payload=response))
    record_audit(session, current_user=current_user, action="PHARMACY_ALERT_ACKNOWLEDGED", resource_type="pharmacy_alert", resource_id=alert.id, new_value={"status": "ACKNOWLEDGED", "note": payload.note, "facility_id": str(facility_id), "pharmacy_location_id": str(alert.pharmacy_location_id) if alert.pharmacy_location_id else None})
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Concurrent alert acknowledgement conflict") from exc
    return response


@router.get("/alert-configuration", response_model=AlertConfigurationRead)
async def get_alert_configuration(
    pharmacy_location_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_permission("PHARMACY_ALERT_VIEW")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    await validate_location(session, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=pharmacy_location_id)
    return await effective_configuration(session, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=pharmacy_location_id)


@router.put("/alert-configuration", response_model=AlertConfigurationRead)
async def put_alert_configuration(
    payload: AlertConfigurationWrite,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_ALERT_CONFIGURE")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    await validate_location(session, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=payload.pharmacy_location_id)
    actor = uuid.UUID(current_user["sub"])
    scope_key = f"location:{payload.pharmacy_location_id}" if payload.pharmacy_location_id else f"facility:{facility_id}"
    digest = _request_hash(payload)
    replay = await _replay(session, tenant_id=tenant_id, user_id=actor, action="CONFIGURE", scope_resource=scope_key, idempotency_key=idempotency_key, request_hash=digest)
    if replay:
        return replay
    configuration = await session.scalar(select(PharmacyAlertConfiguration).where(
        PharmacyAlertConfiguration.tenant_id == tenant_id,
        PharmacyAlertConfiguration.scope_key == scope_key,
    ).with_for_update())
    replay = await _replay(session, tenant_id=tenant_id, user_id=actor, action="CONFIGURE", scope_resource=scope_key, idempotency_key=idempotency_key, request_hash=digest)
    if replay:
        return replay
    if configuration is None and payload.version != 1:
        raise HTTPException(status_code=409, detail="New alert configuration must start at version 1")
    if configuration and configuration.version != payload.version:
        raise HTTPException(status_code=409, detail="Alert configuration version is stale")
    old_value = jsonable_encoder(configuration) if configuration else None
    values = payload.model_dump(exclude={"version"})
    values["high_value_thresholds"] = {code: str(value) for code, value in payload.high_value_thresholds.items()}
    if configuration is None:
        configuration = PharmacyAlertConfiguration(
            tenant_id=tenant_id, facility_id=facility_id, scope_key=scope_key,
            version=1, updated_by=actor, **values,
        )
        session.add(configuration)
    else:
        for key, value in values.items():
            setattr(configuration, key, value)
        configuration.version += 1
        configuration.updated_by = actor
    await session.flush()
    response = {
        **jsonable_encoder(configuration), "scope": "location" if payload.pharmacy_location_id else "facility",
        "effective_from": "location" if payload.pharmacy_location_id else "facility",
    }
    session.add(_operation(tenant_id=tenant_id, facility_id=facility_id, user_id=actor, action="CONFIGURE", scope_resource=scope_key, idempotency_key=idempotency_key, request_hash=digest, response_payload=response))
    record_audit(session, current_user=current_user, action="PHARMACY_ALERT_CONFIGURATION_UPDATED", resource_type="pharmacy_alert_configuration", resource_id=configuration.id, old_value=old_value, new_value=response)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Concurrent alert configuration conflict") from exc
    return response
