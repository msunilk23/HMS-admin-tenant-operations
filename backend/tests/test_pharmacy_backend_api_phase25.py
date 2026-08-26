import inspect

from app.api.v1 import master_data, pharmacy, prescriptions
from app.models.tenant.dosage_form import DosageForm
from app.models.tenant.generic_medicine import GenericMedicine
from app.models.tenant.hospital_formulary import HospitalFormulary
from app.models.tenant.manufacturer import Manufacturer
from app.models.tenant.medicine_product import MedicineProduct
from app.models.tenant.prescription import PrescriptionItem
from app.models.tenant.route import Route
from app.schemas.master_data import (
    DosageFormCreate,
    GenericMedicineCreate,
    HospitalFormularyCreate,
    ManufacturerCreate,
    MedicineProductCreate,
    RouteCreate,
)
from app.schemas.pharmacy import FormularyMedicineSearchResult
from app.schemas.prescription import MedicineItem, PrescriptionItemRead


def test_all_pharmacy_master_search_endpoints_are_registered():
    paths = {route.path for route in master_data.router.routes}
    assert {
        "/generic-medicines",
        "/dosage-forms",
        "/routes",
        "/manufacturers",
        "/medicine-products",
        "/formulary",
    } <= paths
    assert "/medicines/search" in {route.path for route in pharmacy.router.routes}


def test_master_models_have_active_soft_delete_and_tenant_local_unique_codes():
    for model, table_name, constraint_name in (
        (GenericMedicine, "generic_medicines", "uq_generic_medicines_code"),
        (DosageForm, "dosage_forms", "uq_dosage_forms_code"),
        (Route, "routes", "uq_routes_code"),
        (Manufacturer, "manufacturers", "uq_manufacturers_code"),
        (MedicineProduct, "medicine_products", "uq_medicine_products_code"),
    ):
        assert model.__tablename__ == table_name
        assert "is_active" in model.__table__.c
        assert any(constraint.name == constraint_name for constraint in model.__table__.constraints)

    assert {foreign_key.target_fullname for foreign_key in MedicineProduct.__table__.c.generic_medicine_id.foreign_keys} == {"generic_medicines.id"}
    assert {foreign_key.target_fullname for foreign_key in MedicineProduct.__table__.c.dosage_form_id.foreign_keys} == {"dosage_forms.id"}


def test_formulary_has_department_scope_and_unique_assignment():
    assert "department_id" in HospitalFormulary.__table__.c
    assert any(constraint.name == "uq_hospital_formulary_product_department" for constraint in HospitalFormulary.__table__.constraints)


def test_prescription_contract_contains_product_snapshot_and_quantity_controls():
    columns = PrescriptionItem.__table__.c
    assert {
        "medicine_product_id",
        "generic_name_snapshot",
        "brand_name_snapshot",
        "strength_snapshot",
        "dosage_form_snapshot",
        "route_snapshot",
        "auto_quantity",
        "final_quantity",
        "quantity_override_flag",
        "quantity_override_reason",
    } <= set(columns.keys())
    assert {"medicine_product_id", "auto_quantity", "final_quantity", "quantity_override_flag"} <= set(PrescriptionItemRead.model_fields)


def test_p25_schema_contracts_validate_required_shapes():
    assert GenericMedicineCreate(code="PARACETAMOL", name="Paracetamol")
    assert DosageFormCreate(code="TABLET", name="Tablet", calculation_type="UNIT")
    assert RouteCreate(code="ORAL", name="Oral")
    assert ManufacturerCreate(code="CIPLA", name="Cipla")
    assert MedicineProductCreate(code="DOLO-500", generic_medicine_id="00000000-0000-0000-0000-000000000001", dosage_form_id="00000000-0000-0000-0000-000000000002")
    assert HospitalFormularyCreate(medicine_product_id="00000000-0000-0000-0000-000000000001", department_id="00000000-0000-0000-0000-000000000002")
    assert MedicineItem(medicine="External medicine", is_free_text=True, free_text_reason="No formulary alternative")


def test_search_result_excludes_inventory_fields():
    fields = set(FormularyMedicineSearchResult.model_fields)
    assert not fields.intersection({"stock", "stock_quantity", "inventory_quantity", "available_quantity", "batch_id"})


def test_prescription_api_keeps_quantity_calculation_in_normalization_path():
    assert inspect.iscoroutinefunction(prescriptions._normalize_medicine_item)
    assert prescriptions._calculate_unit_quantity(dose="1", frequency="1-0-1-0", duration="5 days") == "10"
    assert prescriptions._calculate_unit_quantity(dose="1", frequency="1-1-1-0", duration="5 days") == "15"
    assert prescriptions._calculate_unit_quantity(dose="1", frequency="BD", duration="1 month") == "60"
    assert prescriptions._calculate_unit_quantity(dose="1", frequency="BD", duration="Ongoing") is None
