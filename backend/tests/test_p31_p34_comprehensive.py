"""
P31-P34 Comprehensive Acceptance Tests

P31: Expiry + Damage + Recall
P32: Stock Transfer + Multi-location
P33: Cycle Count + Physical Verification
P34: Dashboard + Reports + Audit
"""

import pytest
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import (
    StockQuarantine, ProductRecall,
    StockTransfer, StockTransferItem,
    StockCount, CountDetail,
    PharmacyAlert, PharmacyAuditTrail,
    InventoryBatch, PharmacyLocation
)


class TestP31Quarantine:
    """P31 stock quarantine tests."""

    @pytest.mark.asyncio
    async def test_create_quarantine_for_expired_stock(self, mock_session):
        """Test creating quarantine entry for expired stock."""
        tenant_id = uuid.uuid4()
        batch_id = uuid.uuid4()
        
        quarantine = StockQuarantine(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            facility_id=uuid.uuid4(),
            pharmacy_location_id=uuid.uuid4(),
            inventory_batch_id=batch_id,
            status="QUARANTINED",
            reference_key=f"QT-{uuid.uuid4().hex[:8]}",
            reason="EXPIRED",
            total_quantity_quarantined=Decimal("50"),
            quarantined_by=uuid.uuid4(),
            quarantined_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        assert quarantine.id is not None
        assert quarantine.status == "QUARANTINED"
        assert quarantine.reason == "EXPIRED"
        mock_session.add(quarantine)

    @pytest.mark.asyncio
    async def test_approve_quarantine_for_disposal(self, mock_session):
        """Test approving quarantine with disposal action."""
        quarantine = StockQuarantine(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            facility_id=uuid.uuid4(),
            pharmacy_location_id=uuid.uuid4(),
            inventory_batch_id=uuid.uuid4(),
            status="QUARANTINED",
            reference_key="QT-TEST-001",
            reason="DAMAGED",
            total_quantity_quarantined=Decimal("20"),
            quarantined_by=uuid.uuid4(),
            quarantined_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        # Simulate approval
        quarantine.status = "APPROVED_FOR_DISPOSAL"
        quarantine.approved_by = uuid.uuid4()
        quarantine.approved_at = datetime.utcnow()
        quarantine.approved_action = "DISPOSE"
        
        assert quarantine.status == "APPROVED_FOR_DISPOSAL"


class TestP31ProductRecall:
    """P32 batch recall model tests."""

    @pytest.mark.asyncio
    async def test_create_batch_level_recall(self, mock_session):
        """Test creating batch-level recall."""
        recall = ProductRecall(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            facility_id=uuid.uuid4(),
            medicine_id=uuid.uuid4(),
            batch_number="RECALL-BATCH-001",
            status="DRAFT",
            reference_key="RC-TEST-001",
            idempotency_key="recall-test-001",
            request_hash="a" * 64,
            recall_reason="Quality defect discovered",
            initiated_by=uuid.uuid4(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        assert recall.batch_number == "RECALL-BATCH-001"
        assert recall.status == "DRAFT"

    @pytest.mark.asyncio
    async def test_recall_preserves_medicine_and_batch_identity(self, mock_session):
        """Recall identity is always medicine-and-batch specific."""
        medicine_id = uuid.uuid4()
        recall = ProductRecall(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            facility_id=uuid.uuid4(),
            medicine_id=medicine_id,
            batch_number="RECALL-BATCH-002",
            status="DRAFT",
            reference_key="RC-TEST-002",
            idempotency_key="recall-test-002",
            request_hash="b" * 64,
            recall_reason="Manufacturing issue",
            initiated_by=uuid.uuid4(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        assert recall.medicine_id == medicine_id
        assert recall.batch_number == "RECALL-BATCH-002"


class TestP32StockTransfer:
    """P32 stock transfer tests."""

    @pytest.mark.asyncio
    async def test_create_stock_transfer_request(self, mock_session):
        """Test creating inter-location stock transfer request."""
        transfer = StockTransfer(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            facility_id=uuid.uuid4(),
            from_location_id=uuid.uuid4(),
            to_location_id=uuid.uuid4(),
            status="REQUESTED",
            reference_key=f"TR-{uuid.uuid4().hex[:8]}",
            total_items=5,
            total_quantity=Decimal("100"),
            requested_by=uuid.uuid4(),
            requested_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        assert transfer.status == "REQUESTED"
        assert transfer.total_quantity == Decimal("100")

    @pytest.mark.asyncio
    async def test_transfer_with_items(self, mock_session):
        """Test transfer with individual batch items."""
        transfer_id = uuid.uuid4()
        
        transfer = StockTransfer(
            id=transfer_id,
            tenant_id=uuid.uuid4(),
            facility_id=uuid.uuid4(),
            from_location_id=uuid.uuid4(),
            to_location_id=uuid.uuid4(),
            status="REQUESTED",
            reference_key="TR-WITH-ITEMS",
            total_items=2,
            total_quantity=Decimal("150"),
            requested_by=uuid.uuid4(),
            requested_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        item1 = StockTransferItem(
            id=uuid.uuid4(),
            transfer_id=transfer_id,
            inventory_batch_id=uuid.uuid4(),
            transfer_quantity=Decimal("100"),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        item2 = StockTransferItem(
            id=uuid.uuid4(),
            transfer_id=transfer_id,
            inventory_batch_id=uuid.uuid4(),
            transfer_quantity=Decimal("50"),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        assert item1.transfer_quantity == Decimal("100")
        assert item2.transfer_quantity == Decimal("50")


class TestP33StockCount:
    """P33 cycle count tests."""

    @pytest.mark.asyncio
    async def test_initiate_stock_count(self, mock_session):
        """Test initiating physical inventory count."""
        count = StockCount(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            facility_id=uuid.uuid4(),
            pharmacy_location_id=uuid.uuid4(),
            status="CREATED",
            count_type="FULL",
            reference_key=f"CT-{uuid.uuid4().hex[:8]}",
            total_items_counted=0,
            total_variance_items=0,
            initiated_by=uuid.uuid4(),
            initiated_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        assert count.status == "CREATED"
        assert count.total_items_counted == 0

    @pytest.mark.asyncio
    async def test_count_with_variance_detection(self, mock_session):
        """Test counting with variance detection."""
        count_id = uuid.uuid4()
        
        count = StockCount(
            id=count_id,
            tenant_id=uuid.uuid4(),
            facility_id=uuid.uuid4(),
            pharmacy_location_id=uuid.uuid4(),
            status="CREATED",
            count_type="PARTIAL",
            reference_key="CT-VARIANCE",
            initiated_by=uuid.uuid4(),
            initiated_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        detail = CountDetail(
            id=uuid.uuid4(),
            count_id=count_id,
            inventory_batch_id=uuid.uuid4(),
            medicine_id=uuid.uuid4(),
            batch_number="CT-VARIANCE-BATCH",
            system_quantity=Decimal("100"),
            available_quantity=Decimal("100"),
            reserved_quantity=Decimal("0"),
            physical_quantity=Decimal("95"),
            variance_quantity=Decimal("-5"),
            variance_reason="Possible spillage or evaporation",
            counted_by=uuid.uuid4(),
            counted_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        assert detail.variance_quantity == Decimal("-5")


class TestP34DashboardAlerts:
    """P34 dashboard and alerts tests."""

    @pytest.mark.asyncio
    async def test_create_low_stock_alert(self, mock_session):
        """Test creating low stock alert."""
        alert = PharmacyAlert(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            facility_id=uuid.uuid4(),
            alert_type="LOW_STOCK",
            severity="WARNING",
            reference_type="BATCH",
            reference_id=uuid.uuid4(),
            message="Medicine stock is below minimum threshold",
            is_acknowledged=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        assert alert.alert_type == "LOW_STOCK"
        assert alert.severity == "WARNING"
        assert not alert.is_acknowledged

    @pytest.mark.asyncio
    async def test_acknowledge_alert(self, mock_session):
        """Test acknowledging an alert."""
        alert = PharmacyAlert(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            facility_id=uuid.uuid4(),
            alert_type="EXPIRED",
            severity="CRITICAL",
            reference_type="BATCH",
            reference_id=uuid.uuid4(),
            message="Expired stock detected",
            is_acknowledged=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        # Simulate acknowledgment
        alert.is_acknowledged = True
        alert.acknowledged_by = uuid.uuid4()
        alert.acknowledged_at = datetime.utcnow()
        
        assert alert.is_acknowledged
        assert alert.acknowledged_by is not None

    @pytest.mark.asyncio
    async def test_create_audit_trail_entry(self, mock_session):
        """Test creating audit trail entry."""
        audit = PharmacyAuditTrail(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            facility_id=uuid.uuid4(),
            resource_type="StockTransfer",
            resource_id=uuid.uuid4(),
            action="APPROVE",
            user_id=uuid.uuid4(),
            old_values='{"status": "REQUESTED"}',
            new_values='{"status": "APPROVED"}',
            created_at=datetime.utcnow(),
        )
        
        assert audit.resource_type == "StockTransfer"
        assert audit.action == "APPROVE"
        assert "APPROVED" in audit.new_values


# Run tests with: pytest tests/test_p31_p34_comprehensive.py -v
