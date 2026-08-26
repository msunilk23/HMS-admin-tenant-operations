import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import require_permission, require_role
from app.db.engine import get_session
from app.models.tenant.department import Department
from app.models.tenant.dosage_form import DosageForm
from app.models.tenant.generic_medicine import GenericMedicine
from app.models.tenant.hospital_formulary import HospitalFormulary
from app.models.tenant.icd10_code import ICD10Code
from app.models.tenant.manufacturer import Manufacturer
from app.models.tenant.medicine_master import MedicineMaster
from app.models.tenant.medicine_product import MedicineProduct
from app.models.tenant.route import Route
from app.schemas.master_data import (
    DosageFormCreate,
    DosageFormImportItem,
    DosageFormRead,
    DosageFormUpdate,
    GenericMedicineCreate,
    GenericMedicineImportItem,
    GenericMedicineRead,
    GenericMedicineUpdate,
    HospitalFormularyCreate,
    HospitalFormularyImportItem,
    HospitalFormularyRead,
    HospitalFormularyUpdate,
    ICD10ImportItem,
    ICD10Read,
    MedicineImportItem,
    MedicineRead,
    ManufacturerCreate,
    ManufacturerImportItem,
    ManufacturerRead,
    ManufacturerUpdate,
    MedicineProductCreate,
    MedicineProductImportItem,
    MedicineProductRead,
    MedicineProductUpdate,
    RouteCreate,
    RouteImportItem,
    RouteRead,
    RouteUpdate,
)
from app.services.audit_service import record_audit

router = APIRouter(dependencies=[Depends(require_permission("PHARMACY_MASTER_VIEW"))])


def _generic_medicine_values(item: GenericMedicine | None) -> dict | None:
    if item is None:
        return None
    return {
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "therapeutic_class": item.therapeutic_class,
        "is_active": item.is_active,
    }


@router.get("/generic-medicines", response_model=list[GenericMedicineRead])
async def search_generic_medicines(
    q: str = Query("", max_length=100),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "pharmacist", "hospital_admin")),
):
    term = q.strip()
    stmt = select(GenericMedicine).where(GenericMedicine.is_active == True)  # noqa: E712
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                GenericMedicine.code.ilike(like),
                GenericMedicine.name.ilike(like),
                GenericMedicine.therapeutic_class.ilike(like),
            )
        )
    return (await session.execute(stmt.order_by(GenericMedicine.name).limit(limit))).scalars().all()


@router.get("/generic-medicines/{generic_medicine_id}", response_model=GenericMedicineRead)
async def get_generic_medicine(
    generic_medicine_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "pharmacist", "hospital_admin")),
):
    item = await session.get(GenericMedicine, generic_medicine_id)
    if not item:
        raise HTTPException(status_code=404, detail="Generic medicine not found")
    return item


@router.post("/generic-medicines", response_model=GenericMedicineRead, status_code=201)
async def create_generic_medicine(
    payload: GenericMedicineCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_CREATE")),
):
    code = payload.code.strip().upper()
    existing = await session.scalar(select(GenericMedicine).where(GenericMedicine.code == code))
    if existing:
        raise HTTPException(status_code=409, detail="Generic medicine code already exists")
    item = GenericMedicine(
        code=code,
        name=payload.name.strip(),
        description=payload.description,
        therapeutic_class=payload.therapeutic_class,
    )
    session.add(item)
    await session.flush()
    record_audit(
        session,
        current_user=current_user,
        action="CREATE",
        resource_type="generic_medicine",
        resource_id=item.id,
        new_value=_generic_medicine_values(item),
    )
    await session.commit()
    return item


@router.put("/generic-medicines/{generic_medicine_id}", response_model=GenericMedicineRead)
async def update_generic_medicine(
    generic_medicine_id: uuid.UUID,
    payload: GenericMedicineUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_EDIT")),
):
    item = await session.get(GenericMedicine, generic_medicine_id)
    if not item:
        raise HTTPException(status_code=404, detail="Generic medicine not found")
    old_value = _generic_medicine_values(item)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "name" and value is not None:
            value = value.strip()
        setattr(item, field, value)
    record_audit(
        session,
        current_user=current_user,
        action="UPDATE",
        resource_type="generic_medicine",
        resource_id=item.id,
        old_value=old_value,
        new_value=_generic_medicine_values(item),
    )
    await session.commit()
    return item


@router.post("/generic-medicines/{generic_medicine_id}/deactivate", response_model=GenericMedicineRead)
async def deactivate_generic_medicine(
    generic_medicine_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_EDIT")),
):
    item = await session.get(GenericMedicine, generic_medicine_id)
    if not item:
        raise HTTPException(status_code=404, detail="Generic medicine not found")
    if not item.is_active:
        return item
    item.is_active = False
    record_audit(
        session,
        current_user=current_user,
        action="DEACTIVATE",
        resource_type="generic_medicine",
        resource_id=item.id,
        old_value={"is_active": True},
        new_value={"is_active": False},
    )
    await session.commit()
    return item


@router.post("/generic-medicines/import", response_model=list[GenericMedicineRead])
async def import_generic_medicines(
    items: list[GenericMedicineImportItem],
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_CREATE")),
):
    result = []
    for payload in items:
        code = payload.code.strip().upper()
        item = await session.scalar(select(GenericMedicine).where(GenericMedicine.code == code))
        old_value = _generic_medicine_values(item)
        if item:
            item.name = payload.name.strip()
            item.description = payload.description
            item.therapeutic_class = payload.therapeutic_class
            item.is_active = True
            action = "UPDATE"
        else:
            item = GenericMedicine(
                code=code,
                name=payload.name.strip(),
                description=payload.description,
                therapeutic_class=payload.therapeutic_class,
            )
            session.add(item)
            await session.flush()
            action = "CREATE"
        record_audit(
            session,
            current_user=current_user,
            action=action,
            resource_type="generic_medicine",
            resource_id=item.id,
            old_value=old_value,
            new_value=_generic_medicine_values(item),
        )
        result.append(item)
    await session.commit()
    return result


def _dosage_form_values(item: DosageForm | None) -> dict | None:
    if item is None:
        return None
    return {
        "code": item.code,
        "name": item.name,
        "calculation_type": item.calculation_type,
        "description": item.description,
        "is_active": item.is_active,
    }


def _route_values(item: Route | None) -> dict | None:
    if item is None:
        return None
    return {
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "is_active": item.is_active,
    }


@router.get("/dosage-forms", response_model=list[DosageFormRead])
async def search_dosage_forms(
    q: str = Query("", max_length=100),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "pharmacist", "hospital_admin")),
):
    term = q.strip()
    stmt = select(DosageForm).where(DosageForm.is_active == True)  # noqa: E712
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                DosageForm.code.ilike(like),
                DosageForm.name.ilike(like),
                DosageForm.calculation_type.ilike(like),
            )
        )
    return (await session.execute(stmt.order_by(DosageForm.name).limit(limit))).scalars().all()


@router.get("/dosage-forms/{dosage_form_id}", response_model=DosageFormRead)
async def get_dosage_form(
    dosage_form_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "pharmacist", "hospital_admin")),
):
    item = await session.get(DosageForm, dosage_form_id)
    if not item:
        raise HTTPException(status_code=404, detail="Dosage form not found")
    return item


@router.post("/dosage-forms", response_model=DosageFormRead, status_code=201)
async def create_dosage_form(
    payload: DosageFormCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_CREATE")),
):
    code = payload.code.strip().upper()
    if await session.scalar(select(DosageForm).where(DosageForm.code == code)):
        raise HTTPException(status_code=409, detail="Dosage form code already exists")
    item = DosageForm(code=code, name=payload.name.strip(), calculation_type=payload.calculation_type, description=payload.description)
    session.add(item)
    await session.flush()
    record_audit(session, current_user=current_user, action="CREATE", resource_type="dosage_form", resource_id=item.id, new_value=_dosage_form_values(item))
    await session.commit()
    return item


@router.put("/dosage-forms/{dosage_form_id}", response_model=DosageFormRead)
async def update_dosage_form(
    dosage_form_id: uuid.UUID,
    payload: DosageFormUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_EDIT")),
):
    item = await session.get(DosageForm, dosage_form_id)
    if not item:
        raise HTTPException(status_code=404, detail="Dosage form not found")
    old_value = _dosage_form_values(item)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "name" and value is not None:
            value = value.strip()
        setattr(item, field, value)
    record_audit(session, current_user=current_user, action="UPDATE", resource_type="dosage_form", resource_id=item.id, old_value=old_value, new_value=_dosage_form_values(item))
    await session.commit()
    return item


@router.post("/dosage-forms/{dosage_form_id}/deactivate", response_model=DosageFormRead)
async def deactivate_dosage_form(
    dosage_form_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_EDIT")),
):
    item = await session.get(DosageForm, dosage_form_id)
    if not item:
        raise HTTPException(status_code=404, detail="Dosage form not found")
    if item.is_active:
        item.is_active = False
        record_audit(session, current_user=current_user, action="DEACTIVATE", resource_type="dosage_form", resource_id=item.id, old_value={"is_active": True}, new_value={"is_active": False})
        await session.commit()
    return item


@router.post("/dosage-forms/import", response_model=list[DosageFormRead])
async def import_dosage_forms(
    items: list[DosageFormImportItem],
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_CREATE")),
):
    result = []
    for payload in items:
        code = payload.code.strip().upper()
        item = await session.scalar(select(DosageForm).where(DosageForm.code == code))
        old_value = _dosage_form_values(item)
        if item:
            item.name = payload.name.strip()
            item.calculation_type = payload.calculation_type
            item.description = payload.description
            item.is_active = True
            action = "UPDATE"
        else:
            item = DosageForm(code=code, name=payload.name.strip(), calculation_type=payload.calculation_type, description=payload.description)
            session.add(item)
            await session.flush()
            action = "CREATE"
        record_audit(session, current_user=current_user, action=action, resource_type="dosage_form", resource_id=item.id, old_value=old_value, new_value=_dosage_form_values(item))
        result.append(item)
    await session.commit()
    return result


@router.get("/routes", response_model=list[RouteRead])
async def search_routes(
    q: str = Query("", max_length=100),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "pharmacist", "hospital_admin")),
):
    term = q.strip()
    stmt = select(Route).where(Route.is_active == True)  # noqa: E712
    if term:
        like = f"%{term}%"
        stmt = stmt.where(or_(Route.code.ilike(like), Route.name.ilike(like)))
    return (await session.execute(stmt.order_by(Route.name).limit(limit))).scalars().all()


@router.get("/routes/{route_id}", response_model=RouteRead)
async def get_route(
    route_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "pharmacist", "hospital_admin")),
):
    item = await session.get(Route, route_id)
    if not item:
        raise HTTPException(status_code=404, detail="Route not found")
    return item


@router.post("/routes", response_model=RouteRead, status_code=201)
async def create_route(
    payload: RouteCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_CREATE")),
):
    code = payload.code.strip().upper()
    if await session.scalar(select(Route).where(Route.code == code)):
        raise HTTPException(status_code=409, detail="Route code already exists")
    item = Route(code=code, name=payload.name.strip(), description=payload.description)
    session.add(item)
    await session.flush()
    record_audit(session, current_user=current_user, action="CREATE", resource_type="route", resource_id=item.id, new_value=_route_values(item))
    await session.commit()
    return item


@router.put("/routes/{route_id}", response_model=RouteRead)
async def update_route(
    route_id: uuid.UUID,
    payload: RouteUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_EDIT")),
):
    item = await session.get(Route, route_id)
    if not item:
        raise HTTPException(status_code=404, detail="Route not found")
    old_value = _route_values(item)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "name" and value is not None:
            value = value.strip()
        setattr(item, field, value)
    record_audit(session, current_user=current_user, action="UPDATE", resource_type="route", resource_id=item.id, old_value=old_value, new_value=_route_values(item))
    await session.commit()
    return item


@router.post("/routes/{route_id}/deactivate", response_model=RouteRead)
async def deactivate_route(
    route_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_EDIT")),
):
    item = await session.get(Route, route_id)
    if not item:
        raise HTTPException(status_code=404, detail="Route not found")
    if item.is_active:
        item.is_active = False
        record_audit(session, current_user=current_user, action="DEACTIVATE", resource_type="route", resource_id=item.id, old_value={"is_active": True}, new_value={"is_active": False})
        await session.commit()
    return item


@router.post("/routes/import", response_model=list[RouteRead])
async def import_routes(
    items: list[RouteImportItem],
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_CREATE")),
):
    result = []
    for payload in items:
        code = payload.code.strip().upper()
        item = await session.scalar(select(Route).where(Route.code == code))
        old_value = _route_values(item)
        if item:
            item.name = payload.name.strip()
            item.description = payload.description
            item.is_active = True
            action = "UPDATE"
        else:
            item = Route(code=code, name=payload.name.strip(), description=payload.description)
            session.add(item)
            await session.flush()
            action = "CREATE"
        record_audit(session, current_user=current_user, action=action, resource_type="route", resource_id=item.id, old_value=old_value, new_value=_route_values(item))
        result.append(item)
    await session.commit()
    return result


def _manufacturer_values(item: Manufacturer | None) -> dict | None:
    if item is None:
        return None
    return {
        "code": item.code,
        "name": item.name,
        "gstin": item.gstin,
        "country": item.country,
        "is_active": item.is_active,
    }


@router.get("/manufacturers", response_model=list[ManufacturerRead])
async def search_manufacturers(
    q: str = Query("", max_length=100),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "pharmacist", "hospital_admin")),
):
    term = q.strip()
    stmt = select(Manufacturer).where(Manufacturer.is_active == True)  # noqa: E712
    if term:
        like = f"%{term}%"
        stmt = stmt.where(or_(Manufacturer.code.ilike(like), Manufacturer.name.ilike(like)))
    return (await session.execute(stmt.order_by(Manufacturer.name).limit(limit))).scalars().all()


@router.get("/manufacturers/{manufacturer_id}", response_model=ManufacturerRead)
async def get_manufacturer(
    manufacturer_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "pharmacist", "hospital_admin")),
):
    item = await session.get(Manufacturer, manufacturer_id)
    if not item:
        raise HTTPException(status_code=404, detail="Manufacturer not found")
    return item


@router.post("/manufacturers", response_model=ManufacturerRead, status_code=201)
async def create_manufacturer(
    payload: ManufacturerCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_CREATE")),
):
    code = payload.code.strip().upper()
    if await session.scalar(select(Manufacturer).where(Manufacturer.code == code)):
        raise HTTPException(status_code=409, detail="Manufacturer code already exists")
    item = Manufacturer(
        code=code,
        name=payload.name.strip(),
        gstin=payload.gstin,
        country=payload.country,
    )
    session.add(item)
    await session.flush()
    record_audit(session, current_user=current_user, action="CREATE", resource_type="manufacturer", resource_id=item.id, new_value=_manufacturer_values(item))
    await session.commit()
    return item


@router.put("/manufacturers/{manufacturer_id}", response_model=ManufacturerRead)
async def update_manufacturer(
    manufacturer_id: uuid.UUID,
    payload: ManufacturerUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_EDIT")),
):
    item = await session.get(Manufacturer, manufacturer_id)
    if not item:
        raise HTTPException(status_code=404, detail="Manufacturer not found")
    old_value = _manufacturer_values(item)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "name" and value is not None:
            value = value.strip()
        setattr(item, field, value)
    record_audit(session, current_user=current_user, action="UPDATE", resource_type="manufacturer", resource_id=item.id, old_value=old_value, new_value=_manufacturer_values(item))
    await session.commit()
    return item


@router.post("/manufacturers/{manufacturer_id}/deactivate", response_model=ManufacturerRead)
async def deactivate_manufacturer(
    manufacturer_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_EDIT")),
):
    item = await session.get(Manufacturer, manufacturer_id)
    if not item:
        raise HTTPException(status_code=404, detail="Manufacturer not found")
    if item.is_active:
        item.is_active = False
        record_audit(session, current_user=current_user, action="DEACTIVATE", resource_type="manufacturer", resource_id=item.id, old_value={"is_active": True}, new_value={"is_active": False})
        await session.commit()
    return item


@router.post("/manufacturers/import", response_model=list[ManufacturerRead])
async def import_manufacturers(
    items: list[ManufacturerImportItem],
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_CREATE")),
):
    result = []
    for payload in items:
        code = payload.code.strip().upper()
        item = await session.scalar(select(Manufacturer).where(Manufacturer.code == code))
        old_value = _manufacturer_values(item)
        if item:
            item.name = payload.name.strip()
            item.gstin = payload.gstin
            item.country = payload.country
            item.is_active = True
            action = "UPDATE"
        else:
            item = Manufacturer(code=code, name=payload.name.strip(), gstin=payload.gstin, country=payload.country)
            session.add(item)
            await session.flush()
            action = "CREATE"
        record_audit(session, current_user=current_user, action=action, resource_type="manufacturer", resource_id=item.id, old_value=old_value, new_value=_manufacturer_values(item))
        result.append(item)
    await session.commit()
    return result


def _medicine_product_values(item: MedicineProduct | None) -> dict | None:
    if item is None:
        return None
    return {
        "code": item.code,
        "generic_medicine_id": str(item.generic_medicine_id),
        "brand_name": item.brand_name,
        "strength": item.strength,
        "unit": item.unit,
        "dosage_form_id": str(item.dosage_form_id),
        "default_route_id": str(item.default_route_id) if item.default_route_id else None,
        "manufacturer_id": str(item.manufacturer_id) if item.manufacturer_id else None,
        "composition": item.composition,
        "hsn_code": item.hsn_code,
        "gst_rate": str(item.gst_rate) if item.gst_rate is not None else None,
        "schedule_category": item.schedule_category,
        "is_controlled_drug": item.is_controlled_drug,
        "requires_prescription": item.requires_prescription,
        "is_active": item.is_active,
    }


async def _validate_product_references(session: AsyncSession, payload) -> None:
    required_refs = (
        (GenericMedicine, payload.generic_medicine_id, "Generic medicine"),
        (DosageForm, payload.dosage_form_id, "Dosage form"),
    )
    for model, item_id, label in required_refs:
        item = await session.get(model, item_id)
        if not item or not item.is_active:
            raise HTTPException(status_code=422, detail=f"{label} is missing or inactive")

    optional_refs = (
        (Route, payload.default_route_id, "Route"),
        (Manufacturer, payload.manufacturer_id, "Manufacturer"),
    )
    for model, item_id, label in optional_refs:
        if item_id is None:
            continue
        item = await session.get(model, item_id)
        if not item or not item.is_active:
            raise HTTPException(status_code=422, detail=f"{label} is missing or inactive")


@router.get("/medicine-products", response_model=list[MedicineProductRead])
async def search_medicine_products(
    q: str = Query("", max_length=100),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "pharmacist", "hospital_admin")),
):
    term = q.strip()
    stmt = select(MedicineProduct).where(MedicineProduct.is_active == True)  # noqa: E712
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                MedicineProduct.code.ilike(like),
                MedicineProduct.brand_name.ilike(like),
                MedicineProduct.strength.ilike(like),
                MedicineProduct.composition.ilike(like),
            )
        )
    return (await session.execute(stmt.order_by(MedicineProduct.code).limit(limit))).scalars().all()


@router.get("/medicine-products/{medicine_product_id}", response_model=MedicineProductRead)
async def get_medicine_product(
    medicine_product_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "pharmacist", "hospital_admin")),
):
    item = await session.get(MedicineProduct, medicine_product_id)
    if not item:
        raise HTTPException(status_code=404, detail="Medicine product not found")
    return item


@router.post("/medicine-products", response_model=MedicineProductRead, status_code=201)
async def create_medicine_product(
    payload: MedicineProductCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_CREATE")),
):
    code = payload.code.strip().upper()
    if await session.scalar(select(MedicineProduct).where(MedicineProduct.code == code)):
        raise HTTPException(status_code=409, detail="Medicine product code already exists")
    await _validate_product_references(session, payload)
    item = MedicineProduct(code=code, **payload.model_dump(exclude={"code"}))
    session.add(item)
    await session.flush()
    record_audit(session, current_user=current_user, action="CREATE", resource_type="medicine_product", resource_id=item.id, new_value=_medicine_product_values(item))
    await session.commit()
    return item


@router.put("/medicine-products/{medicine_product_id}", response_model=MedicineProductRead)
async def update_medicine_product(
    medicine_product_id: uuid.UUID,
    payload: MedicineProductUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_EDIT")),
):
    item = await session.get(MedicineProduct, medicine_product_id)
    if not item:
        raise HTTPException(status_code=404, detail="Medicine product not found")
    changes = payload.model_dump(exclude_unset=True)
    reference_payload = type("ProductReferences", (), {
        "generic_medicine_id": changes.get("generic_medicine_id", item.generic_medicine_id),
        "dosage_form_id": changes.get("dosage_form_id", item.dosage_form_id),
        "default_route_id": changes.get("default_route_id", item.default_route_id),
        "manufacturer_id": changes.get("manufacturer_id", item.manufacturer_id),
    })()
    await _validate_product_references(session, reference_payload)
    old_value = _medicine_product_values(item)
    for field, value in changes.items():
        setattr(item, field, value)
    record_audit(session, current_user=current_user, action="UPDATE", resource_type="medicine_product", resource_id=item.id, old_value=old_value, new_value=_medicine_product_values(item))
    await session.commit()
    return item


@router.post("/medicine-products/{medicine_product_id}/deactivate", response_model=MedicineProductRead)
async def deactivate_medicine_product(
    medicine_product_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_EDIT")),
):
    item = await session.get(MedicineProduct, medicine_product_id)
    if not item:
        raise HTTPException(status_code=404, detail="Medicine product not found")
    if item.is_active:
        item.is_active = False
        record_audit(session, current_user=current_user, action="DEACTIVATE", resource_type="medicine_product", resource_id=item.id, old_value={"is_active": True}, new_value={"is_active": False})
        await session.commit()
    return item


@router.post("/medicine-products/import", response_model=list[MedicineProductRead])
async def import_medicine_products(
    items: list[MedicineProductImportItem],
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_MASTER_CREATE")),
):
    result = []
    for payload in items:
        code = payload.code.strip().upper()
        await _validate_product_references(session, payload)
        item = await session.scalar(select(MedicineProduct).where(MedicineProduct.code == code))
        old_value = _medicine_product_values(item)
        values = payload.model_dump(exclude={"code"})
        if item:
            for field, value in values.items():
                setattr(item, field, value)
            item.is_active = True
            action = "UPDATE"
        else:
            item = MedicineProduct(code=code, **values)
            session.add(item)
            await session.flush()
            action = "CREATE"
        record_audit(session, current_user=current_user, action=action, resource_type="medicine_product", resource_id=item.id, old_value=old_value, new_value=_medicine_product_values(item))
        result.append(item)
    await session.commit()
    return result


def _hospital_formulary_values(item: HospitalFormulary | None) -> dict | None:
    if item is None:
        return None
    return {
        "medicine_product_id": str(item.medicine_product_id),
        "department_id": str(item.department_id),
        "is_approved": item.is_approved,
        "is_preferred": item.is_preferred,
        "is_prescribable": item.is_prescribable,
        "effective_date": item.effective_date.isoformat() if item.effective_date else None,
        "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
        "is_active": item.is_active,
    }


async def _validate_formulary_references(session: AsyncSession, medicine_product_id: uuid.UUID, department_id: uuid.UUID) -> None:
    product = await session.get(MedicineProduct, medicine_product_id)
    if not product or not product.is_active:
        raise HTTPException(status_code=422, detail="Medicine product is missing or inactive")
    department = await session.get(Department, department_id)
    if not department or not department.is_active:
        raise HTTPException(status_code=422, detail="Department is missing or inactive")


@router.get("/formulary", response_model=list[HospitalFormularyRead])
async def search_hospital_formulary(
    q: str = Query("", max_length=100),
    department_id: uuid.UUID | None = None,
    prescribable_only: bool = False,
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "pharmacist", "hospital_admin")),
):
    stmt = (
        select(HospitalFormulary)
        .join(MedicineProduct, MedicineProduct.id == HospitalFormulary.medicine_product_id)
        .where(
            HospitalFormulary.is_active == True,  # noqa: E712
            MedicineProduct.is_active == True,  # noqa: E712
        )
    )
    if department_id is not None:
        stmt = stmt.where(HospitalFormulary.department_id == department_id)
    if prescribable_only:
        stmt = stmt.where(HospitalFormulary.is_prescribable == True)  # noqa: E712
    term = q.strip()
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                MedicineProduct.code.ilike(like),
                MedicineProduct.brand_name.ilike(like),
                MedicineProduct.strength.ilike(like),
                MedicineProduct.composition.ilike(like),
            )
        )
    return (await session.execute(stmt.order_by(HospitalFormulary.created_at.desc()).limit(limit))).scalars().all()


@router.get("/formulary/{formulary_id}", response_model=HospitalFormularyRead)
async def get_hospital_formulary(
    formulary_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "pharmacist", "hospital_admin")),
):
    item = await session.get(HospitalFormulary, formulary_id)
    if not item:
        raise HTTPException(status_code=404, detail="Hospital formulary entry not found")
    return item


@router.post("/formulary", response_model=HospitalFormularyRead, status_code=201)
async def create_hospital_formulary(
    payload: HospitalFormularyCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_FORMULARY_MANAGE")),
):
    await _validate_formulary_references(session, payload.medicine_product_id, payload.department_id)
    existing = await session.scalar(
        select(HospitalFormulary).where(
            HospitalFormulary.medicine_product_id == payload.medicine_product_id,
            HospitalFormulary.department_id == payload.department_id,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Medicine product is already assigned to this department")
    item = HospitalFormulary(**payload.model_dump())
    session.add(item)
    await session.flush()
    record_audit(session, current_user=current_user, action="CREATE", resource_type="hospital_formulary", resource_id=item.id, new_value=_hospital_formulary_values(item))
    await session.commit()
    return item


@router.put("/formulary/{formulary_id}", response_model=HospitalFormularyRead)
async def update_hospital_formulary(
    formulary_id: uuid.UUID,
    payload: HospitalFormularyUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_FORMULARY_MANAGE")),
):
    item = await session.get(HospitalFormulary, formulary_id)
    if not item:
        raise HTTPException(status_code=404, detail="Hospital formulary entry not found")
    old_value = _hospital_formulary_values(item)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    record_audit(session, current_user=current_user, action="UPDATE", resource_type="hospital_formulary", resource_id=item.id, old_value=old_value, new_value=_hospital_formulary_values(item))
    await session.commit()
    return item


@router.post("/formulary/{formulary_id}/deactivate", response_model=HospitalFormularyRead)
async def deactivate_hospital_formulary(
    formulary_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_FORMULARY_MANAGE")),
):
    item = await session.get(HospitalFormulary, formulary_id)
    if not item:
        raise HTTPException(status_code=404, detail="Hospital formulary entry not found")
    if item.is_active:
        item.is_active = False
        record_audit(session, current_user=current_user, action="DEACTIVATE", resource_type="hospital_formulary", resource_id=item.id, old_value={"is_active": True}, new_value={"is_active": False})
        await session.commit()
    return item


@router.post("/formulary/import", response_model=list[HospitalFormularyRead])
async def import_hospital_formulary(
    items: list[HospitalFormularyImportItem],
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_FORMULARY_MANAGE")),
):
    result = []
    for payload in items:
        await _validate_formulary_references(session, payload.medicine_product_id, payload.department_id)
        item = await session.scalar(
            select(HospitalFormulary).where(
                HospitalFormulary.medicine_product_id == payload.medicine_product_id,
                HospitalFormulary.department_id == payload.department_id,
            )
        )
        old_value = _hospital_formulary_values(item)
        if item:
            for field, value in payload.model_dump().items():
                setattr(item, field, value)
            item.is_active = True
            action = "UPDATE"
        else:
            item = HospitalFormulary(**payload.model_dump())
            session.add(item)
            await session.flush()
            action = "CREATE"
        record_audit(session, current_user=current_user, action=action, resource_type="hospital_formulary", resource_id=item.id, old_value=old_value, new_value=_hospital_formulary_values(item))
        result.append(item)
    await session.commit()
    return result


@router.get("/icd10", response_model=list[ICD10Read])
async def search_icd10(q: str = Query("", max_length=100), limit: int = Query(20, ge=1, le=100), session: AsyncSession = Depends(get_session), _: dict = Depends(require_role("doctor", "hospital_admin"))):
    term = q.strip()
    stmt = select(ICD10Code).where(ICD10Code.is_active == True)  # noqa: E712
    if term:
        stmt = stmt.where(or_(ICD10Code.code.ilike(f"%{term}%"), ICD10Code.description.ilike(f"%{term}%")))
    rows = (await session.execute(stmt.order_by(ICD10Code.code).limit(limit))).scalars().all()
    return rows


@router.get("/medicines", response_model=list[MedicineRead])
async def search_medicines(q: str = Query("", max_length=100), limit: int = Query(20, ge=1, le=100), session: AsyncSession = Depends(get_session), _: dict = Depends(require_role("doctor", "pharmacist", "hospital_admin"))):
    term = q.strip()
    stmt = select(MedicineMaster).where(MedicineMaster.is_active == True)  # noqa: E712
    if term:
        like = f"%{term}%"
        stmt = stmt.where(or_(MedicineMaster.generic_name.ilike(like), MedicineMaster.brand_name.ilike(like), MedicineMaster.strength.ilike(like), MedicineMaster.dosage_form.ilike(like)))
    rows = (await session.execute(stmt.order_by(MedicineMaster.generic_name).limit(limit))).scalars().all()
    return rows


@router.post("/icd10/import", response_model=list[ICD10Read])
async def import_icd10(items: list[ICD10ImportItem], session: AsyncSession = Depends(get_session), _: dict = Depends(require_role("hospital_admin"))):
    result = []
    for item in items:
        existing = (await session.execute(select(ICD10Code).where(ICD10Code.code == item.code))).scalar_one_or_none()
        if existing:
            existing.description = item.description
            existing.is_active = True
        else:
            existing = ICD10Code(id=uuid.uuid4(), code=item.code, description=item.description)
            session.add(existing)
        result.append(existing)
    await session.commit()
    return result


@router.post("/medicines/import", response_model=list[MedicineRead])
async def import_medicines(items: list[MedicineImportItem], session: AsyncSession = Depends(get_session), _: dict = Depends(require_role("hospital_admin"))):
    result = []
    for item in items:
        existing = (await session.execute(select(MedicineMaster).where(MedicineMaster.generic_name == item.generic_name, MedicineMaster.brand_name == item.brand_name, MedicineMaster.strength == item.strength, MedicineMaster.dosage_form == item.dosage_form))).scalar_one_or_none()
        if existing:
            existing.instructions = item.instructions
            existing.is_active = True
        else:
            existing = MedicineMaster(id=uuid.uuid4(), **item.model_dump())
            session.add(existing)
        result.append(existing)
    await session.commit()
    return result
