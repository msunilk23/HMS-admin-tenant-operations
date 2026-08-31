import os
import socket
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.api.v1.pharmacy_dashboard import _csv_value, acknowledge_alert, put_alert_configuration
from app.models.tenant import InventoryBatch, PharmacyAlert, PharmacyAlertAcknowledgement, PharmacyAlertConfiguration, PharmacyDashboardOperation, PharmacyLocation
from app.schemas.pharmacy_dashboard import AlertAcknowledgeRequest, AlertConfigurationWrite
from app.services.pharmacy_dashboard_service import business_window, dashboard_cards, recalculate_alerts, report_rows

PG_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital")


def _reachable():
    parsed = urlparse(PG_URL.replace("+asyncpg", ""))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 5432), timeout=1.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="PostgreSQL is not reachable")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def context():
    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    schema = f"p34_{uuid.uuid4().hex[:8]}"
    ids = {name: uuid.uuid4() for name in ("tenant", "facility", "other_facility", "location", "other_location", "medicine", "actor")}
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET search_path TO "{schema}", public'))
        tables = [table for table in Base.metadata.sorted_tables if table.schema is None]
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    session = maker()
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    session.add_all([
        PharmacyLocation(id=ids["location"], tenant_id=ids["tenant"], facility_id=ids["facility"], location_code="P34-A", location_name="P34 Pharmacy", location_type="PHARMACY", active=True),
        PharmacyLocation(id=ids["other_location"], tenant_id=ids["tenant"], facility_id=ids["other_facility"], location_code="P34-B", location_name="Other Pharmacy", location_type="PHARMACY", active=True),
    ])
    await session.flush()
    own_batch = InventoryBatch(tenant_id=ids["tenant"], facility_id=ids["facility"], pharmacy_location_id=ids["location"], medicine_id=ids["medicine"], batch_number="P34-OWN", expiry_date=date.today() + timedelta(days=10), purchase_rate=Decimal("12.34"), received_quantity=Decimal("5"), available_quantity=Decimal("5"), reserved_quantity=Decimal("0"), status="ACTIVE")
    other_batch = InventoryBatch(tenant_id=ids["tenant"], facility_id=ids["other_facility"], pharmacy_location_id=ids["other_location"], medicine_id=ids["medicine"], batch_number="P34-OTHER", expiry_date=date.today() + timedelta(days=10), purchase_rate=Decimal("999"), received_quantity=Decimal("999"), available_quantity=Decimal("999"), reserved_quantity=Decimal("0"), status="ACTIVE")
    session.add_all([own_batch, other_batch, PharmacyAlertConfiguration(tenant_id=ids["tenant"], facility_id=ids["facility"], scope_key=f'facility:{ids["facility"]}', reorder_level=Decimal("10"), expiry_horizon_days=90, high_value_thresholds={"INR": "5000.00"}, quantity_percentage_threshold=Decimal("10"), repeated_event_count=2, lookback_days=90, version=1, updated_by=ids["actor"])])
    await session.commit()
    yield {**ids, "engine": engine, "schema": schema, "maker": maker, "session": session, "own_batch": own_batch}
    await session.close()
    async with engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await engine.dispose()


@pytest.mark.asyncio(loop_scope="module")
async def test_business_date_timezone_and_facility_isolated_dashboard(context):
    effective_date, start, end, timezone_name = business_window("Asia/Kolkata", date(2026, 8, 31))
    assert effective_date == date(2026, 8, 31)
    assert timezone_name == "Asia/Kolkata"
    assert start == datetime(2026, 8, 30, 18, 30, tzinfo=timezone.utc)
    assert end - start == timedelta(days=1)

    result = await dashboard_cards(context["session"], tenant_id=context["tenant"], facility_id=context["facility"], pharmacy_location_id=None, timezone_name="Asia/Kolkata", financial_data_visible=False)
    assert result["cards"]["low_stock_items"] == 1
    assert result["cards"]["inventory_valuation"]["available"] is None
    assert result["cards"]["inventory_valuation"]["total_physical"] is None
    assert result["cards"]["inventory_valuation"]["unvalued_quantity"] == 0


@pytest.mark.asyncio(loop_scope="module")
async def test_reports_filter_isolate_validate_and_classify(context):
    today = date.today()
    stock = await report_rows(context["session"], report="current-stock", tenant_id=context["tenant"], facility_id=context["facility"], pharmacy_location_id=context["location"], timezone_name="UTC", start_date=today - timedelta(days=30), end_date=today, page=1, page_size=50, batch_number="OWN")
    assert stock["total"] == 1
    assert stock["items"][0]["batch_number"] == "P34-OWN"
    assert stock["filters"]["batch_number"] == "OWN"

    movement = await report_rows(context["session"], report="inventory-movement", tenant_id=context["tenant"], facility_id=context["facility"], pharmacy_location_id=None, timezone_name="UTC", start_date=today - timedelta(days=90), end_date=today, page=1, page_size=50)
    assert movement["total"] == 1
    assert movement["items"][0]["classification"] == "NON_MOVING"
    assert movement["items"][0]["current_inventory_quantity"] == Decimal("5.000")

    with pytest.raises(HTTPException, match="Unknown Pharmacy report") as unknown:
        await report_rows(context["session"], report="not-a-report", tenant_id=context["tenant"], facility_id=context["facility"], pharmacy_location_id=None, timezone_name="UTC", start_date=today, end_date=today, page=1, page_size=50)
    assert unknown.value.status_code == 404
    with pytest.raises(HTTPException, match="date range") as invalid_range:
        await report_rows(context["session"], report="current-stock", tenant_id=context["tenant"], facility_id=context["facility"], pharmacy_location_id=None, timezone_name="UTC", start_date=today, end_date=today - timedelta(days=1), page=1, page_size=50)
    assert invalid_range.value.status_code == 422
    with pytest.raises(HTTPException, match="location") as wrong_facility:
        await report_rows(context["session"], report="current-stock", tenant_id=context["tenant"], facility_id=context["facility"], pharmacy_location_id=context["other_location"], timezone_name="UTC", start_date=today, end_date=today, page=1, page_size=50)
    assert wrong_facility.value.status_code == 404


@pytest.mark.asyncio(loop_scope="module")
async def test_alert_recalculation_deduplicates_resolves_and_links_recurrence(context):
    session = context["session"]
    first = await recalculate_alerts(session, tenant_id=context["tenant"], facility_id=context["facility"], pharmacy_location_id=context["location"], timezone_name="UTC")
    await session.commit()
    assert first == {"created": 2, "updated": 0, "resolved": 0, "active": 2}
    initial = (await session.execute(select(PharmacyAlert).order_by(PharmacyAlert.alert_type))).scalars().all()
    assert {alert.alert_type for alert in initial} == {"LOW_STOCK", "EXPIRY"}

    second = await recalculate_alerts(session, tenant_id=context["tenant"], facility_id=context["facility"], pharmacy_location_id=context["location"], timezone_name="UTC")
    await session.commit()
    assert second == {"created": 0, "updated": 2, "resolved": 0, "active": 2}
    assert len((await session.execute(select(PharmacyAlert))).scalars().all()) == 2

    context["own_batch"].available_quantity = Decimal("20")
    context["own_batch"].expiry_date = date.today() + timedelta(days=400)
    await session.commit()
    cleared = await recalculate_alerts(session, tenant_id=context["tenant"], facility_id=context["facility"], pharmacy_location_id=context["location"], timezone_name="UTC")
    await session.commit()
    assert cleared == {"created": 0, "updated": 0, "resolved": 2, "active": 0}
    assert all(alert.status == "RESOLVED" and alert.active_subject_key is None for alert in initial)

    context["own_batch"].available_quantity = Decimal("5")
    context["own_batch"].expiry_date = date.today() + timedelta(days=10)
    await session.commit()
    recurrence = await recalculate_alerts(session, tenant_id=context["tenant"], facility_id=context["facility"], pharmacy_location_id=context["location"], timezone_name="UTC")
    await session.commit()
    assert recurrence == {"created": 2, "updated": 0, "resolved": 0, "active": 2}
    active = (await session.execute(select(PharmacyAlert).where(PharmacyAlert.status == "OPEN"))).scalars().all()
    assert len(active) == 2
    assert all(alert.previous_alert_id is not None for alert in active)


@pytest.mark.asyncio(loop_scope="module")
async def test_mutation_idempotency_version_conflicts_and_csv_safety(context):
    session = context["session"]
    user = {"sub": str(context["actor"]), "role": "store_manager", "tenant_id": str(context["tenant"]), "tenant_schema": context["schema"], "facility_id": str(context["facility"])}
    alert = await session.scalar(select(PharmacyAlert).where(PharmacyAlert.status == "OPEN", PharmacyAlert.alert_type == "LOW_STOCK"))
    payload = AlertAcknowledgeRequest(note="Reviewed and replenishment assigned")
    first = await acknowledge_alert(alert.id, payload, "p34-ack-key", session, user, context["tenant"], context["facility"])
    replay = await acknowledge_alert(alert.id, payload, "p34-ack-key", session, user, context["tenant"], context["facility"])
    assert str(first.id) == replay["id"]
    assert await session.scalar(select(func.count()).select_from(PharmacyAlertAcknowledgement).where(PharmacyAlertAcknowledgement.alert_id == alert.id)) == 1
    assert await session.scalar(select(func.count()).select_from(PharmacyDashboardOperation).where(PharmacyDashboardOperation.action == "ACKNOWLEDGE")) == 1
    with pytest.raises(HTTPException, match="different payload") as reused:
        await acknowledge_alert(alert.id, AlertAcknowledgeRequest(note="Different acknowledgement note"), "p34-ack-key", session, user, context["tenant"], context["facility"])
    assert reused.value.status_code == 409

    configuration = AlertConfigurationWrite(reorder_level=Decimal("12"), expiry_horizon_days=120, version=1)
    configured = await put_alert_configuration(configuration, "p34-config-key", session, user, context["tenant"], context["facility"])
    configured_replay = await put_alert_configuration(configuration, "p34-config-key", session, user, context["tenant"], context["facility"])
    assert configured_replay["id"] == configured["id"]
    assert configured["version"] == 2
    with pytest.raises(HTTPException, match="different payload") as config_reused:
        await put_alert_configuration(AlertConfigurationWrite(reorder_level=Decimal("13"), expiry_horizon_days=120, version=1), "p34-config-key", session, user, context["tenant"], context["facility"])
    assert config_reused.value.status_code == 409
    with pytest.raises(HTTPException, match="stale") as stale:
        await put_alert_configuration(configuration, "p34-stale-key", session, user, context["tenant"], context["facility"])
    assert stale.value.status_code == 409
    assert await session.scalar(select(func.count()).select_from(PharmacyDashboardOperation).where(PharmacyDashboardOperation.action == "CONFIGURE")) == 1

    assert _csv_value("=2+3") == "'=2+3"
    assert _csv_value("+SUM(A1:A2)") == "'+SUM(A1:A2)"
    assert _csv_value("-1") == "'-1"
    assert _csv_value("@command") == "'@command"
    assert _csv_value("ordinary") == "ordinary"
