import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import require_role
from app.db.engine import get_session
from app.models.tenant.icd10_code import ICD10Code
from app.models.tenant.medicine_master import MedicineMaster
from app.schemas.master_data import ICD10ImportItem, ICD10Read, MedicineImportItem, MedicineRead

router = APIRouter()


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
