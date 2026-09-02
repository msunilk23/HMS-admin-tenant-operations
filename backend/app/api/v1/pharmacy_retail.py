import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_facility_id, get_tenant_id_from_token
from app.core.dependencies import require_feature, require_role
from app.db.engine import get_session
from app.models.public.user import User
from app.models.tenant.pharmacy_location import PharmacyLocation
from app.models.tenant.pharmacy_retail_sale import (
    PharmacistLocationAuthorization,
    PharmacyRetailConfiguration,
    PharmacyRetailSale,
    PharmacyRetailSaleItem,
)
from app.schemas.pharmacy_retail import (
    PharmacistAuthorizationCreate,
    PharmacistAuthorizationRead,
    RetailConfigurationRead,
    RetailConfigurationWrite,
    RetailMedicineRead,
    RetailReturnCreate,
    RetailReturnRead,
    RetailSaleCreate,
    RetailSaleDispense,
    RetailSaleItemRead,
    RetailSaleRead,
)
from app.services.audit_service import record_audit
from app.services.pharmacy_retail_service import (
    create_retail_sale,
    dispense_retail_sale,
    require_authorized_pharmacist,
    retail_configuration,
    return_retail_sale,
    search_retail_medicines,
    verify_external_sale,
)

router = APIRouter(dependencies=[Depends(require_feature("pharmacy"))])


def _error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


async def _sale_read(session: AsyncSession, sale: PharmacyRetailSale) -> RetailSaleRead:
    response = RetailSaleRead.model_validate(sale)
    response.items = [
        RetailSaleItemRead.model_validate(item)
        for item in (await session.execute(
            select(PharmacyRetailSaleItem).where(PharmacyRetailSaleItem.sale_id == sale.id).order_by(PharmacyRetailSaleItem.created_at)
        )).scalars().all()
    ]
    return response


async def _scoped_sale(
    session: AsyncSession, sale_id: uuid.UUID, tenant_id: uuid.UUID, facility_id: uuid.UUID,
) -> PharmacyRetailSale:
    sale = await session.scalar(select(PharmacyRetailSale).where(
        PharmacyRetailSale.id == sale_id,
        PharmacyRetailSale.tenant_id == tenant_id,
        PharmacyRetailSale.facility_id == facility_id,
    ))
    if sale is None:
        raise HTTPException(status_code=404, detail="Retail sale not found")
    return sale


@router.get("/medicines", response_model=list[RetailMedicineRead])
async def search_medicines(
    pharmacy_location_id: uuid.UUID,
    q: str = Query("", max_length=100),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("pharmacist")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    actor_id = uuid.UUID(current_user["sub"])
    try:
        await require_authorized_pharmacist(
            session, user_id=actor_id, tenant_id=tenant_id, facility_id=facility_id,
            pharmacy_location_id=pharmacy_location_id,
        )
        return await search_retail_medicines(
            session, query=q.strip(), tenant_id=tenant_id, facility_id=facility_id, location_id=pharmacy_location_id,
        )
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/sales", response_model=RetailSaleRead, status_code=201)
async def create_sale(
    payload: RetailSaleCreate,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("pharmacist")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    try:
        sale = await create_retail_sale(
            session, payload=payload, idempotency_key=idempotency_key, tenant_id=tenant_id,
            facility_id=facility_id, actor_id=uuid.UUID(current_user["sub"]), current_user=current_user,
        )
        return await _sale_read(session, sale)
    except ValueError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.get("/sales/{sale_id}", response_model=RetailSaleRead)
async def get_sale(
    sale_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("pharmacist", "hospital_admin")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    sale = await _scoped_sale(session, sale_id, tenant_id, facility_id)
    if current_user["role"] == "pharmacist":
        try:
            await require_authorized_pharmacist(
                session, user_id=uuid.UUID(current_user["sub"]), tenant_id=tenant_id,
                facility_id=facility_id, pharmacy_location_id=sale.pharmacy_location_id,
            )
        except ValueError as exc:
            raise _error(exc) from exc
    return await _sale_read(session, sale)


@router.post("/sales/{sale_id}/verify", response_model=RetailSaleRead)
async def verify_sale(
    sale_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("pharmacist")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    try:
        sale = await verify_external_sale(
            session, sale_id=sale_id, tenant_id=tenant_id, facility_id=facility_id,
            actor_id=uuid.UUID(current_user["sub"]), current_user=current_user,
        )
        return await _sale_read(session, sale)
    except ValueError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.post("/sales/{sale_id}/dispense", response_model=RetailSaleRead)
async def dispense_sale(
    sale_id: uuid.UUID,
    payload: RetailSaleDispense,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("pharmacist")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    try:
        sale = await dispense_retail_sale(
            session, sale_id=sale_id, payload=payload, tenant_id=tenant_id,
            facility_id=facility_id, actor_id=uuid.UUID(current_user["sub"]), current_user=current_user,
        )
        return await _sale_read(session, sale)
    except ValueError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.post("/sales/{sale_id}/returns", response_model=RetailReturnRead, status_code=201)
async def return_sale(
    sale_id: uuid.UUID,
    payload: RetailReturnCreate,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("pharmacist")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    try:
        return await return_retail_sale(
            session, sale_id=sale_id, payload=payload, idempotency_key=idempotency_key,
            tenant_id=tenant_id, facility_id=facility_id,
            actor_id=uuid.UUID(current_user["sub"]), current_user=current_user,
        )
    except ValueError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.get("/configuration", response_model=RetailConfigurationRead)
async def get_configuration(
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("pharmacist", "hospital_admin")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
):
    return await retail_configuration(session, tenant_id)


@router.put("/configuration", response_model=RetailConfigurationRead)
async def update_configuration(
    payload: RetailConfigurationWrite,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
):
    configuration = await retail_configuration(session, tenant_id)
    old_value = {
        "non_controlled_validity_days": configuration.non_controlled_validity_days,
        "non_controlled_max_supply_days": configuration.non_controlled_max_supply_days,
        "controlled_validity_days": configuration.controlled_validity_days,
        "controlled_max_supply_days": configuration.controlled_max_supply_days,
    }
    for field, value in payload.model_dump().items():
        setattr(configuration, field, value)
    configuration.updated_by = uuid.UUID(current_user["sub"])
    record_audit(
        session, current_user=current_user, action="UPDATE", resource_type="pharmacy_retail_configuration",
        resource_id=configuration.id, old_value=old_value, new_value=payload.model_dump(),
    )
    await session.commit()
    return configuration


@router.post("/authorizations", response_model=PharmacistAuthorizationRead, status_code=201)
async def authorize_pharmacist(
    payload: PharmacistAuthorizationCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
    tenant_id: uuid.UUID = Depends(get_tenant_id_from_token),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    user = await session.scalar(select(User).where(
        User.id == payload.user_id, User.tenant_id == tenant_id, User.role == "pharmacist", User.is_active.is_(True),
    ))
    location = await session.scalar(select(PharmacyLocation).where(
        PharmacyLocation.id == payload.pharmacy_location_id, PharmacyLocation.tenant_id == tenant_id,
        PharmacyLocation.facility_id == facility_id, PharmacyLocation.active.is_(True),
    ))
    if user is None or location is None:
        raise HTTPException(status_code=422, detail="Active Pharmacist and Pharmacy location must belong to this tenant facility")
    authorization = await session.scalar(select(PharmacistLocationAuthorization).where(
        PharmacistLocationAuthorization.tenant_id == tenant_id,
        PharmacistLocationAuthorization.facility_id == facility_id,
        PharmacistLocationAuthorization.pharmacy_location_id == payload.pharmacy_location_id,
        PharmacistLocationAuthorization.user_id == payload.user_id,
    ))
    if authorization is None:
        authorization = PharmacistLocationAuthorization(
            tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=payload.pharmacy_location_id,
            user_id=payload.user_id, authorized_by=uuid.UUID(current_user["sub"]),
        )
        session.add(authorization)
    else:
        authorization.is_active = True
        authorization.authorized_by = uuid.UUID(current_user["sub"])
    record_audit(
        session, current_user=current_user, action="AUTHORIZE", resource_type="pharmacist_location_authorization",
        resource_id=authorization.id, new_value={"user_id": str(payload.user_id), "pharmacy_location_id": str(payload.pharmacy_location_id)},
    )
    await session.commit()
    return authorization