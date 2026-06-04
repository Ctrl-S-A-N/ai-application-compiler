"""Phase 4 – Validation Engine tests.

Independent tests for the deterministic, rule-based validation engine.
Negative tests construct broken schemas via model_dump → modify → model_validate
to trigger each cross-layer check in isolation.
"""

from pathlib import Path

from compiler.architecture_planner import plan_architecture
from compiler.contracts import (
    APIFieldSchema,
    APIModelSchema,
    APISchema,
    AppSpec,
    AuthAccessPolicy,
    AuthSchema,
    CompilerStage,
    DatabaseSchema,
    FieldType,
    UIFormSchema,
    UISchema,
    ValidationReport,
    ValidationSeverity,
)
from compiler.intent_extractor import extract_intent
from compiler.logging import read_stage_log
from compiler.schema_generators.api_generator import generate_api_schema
from compiler.schema_generators.auth_generator import generate_auth_schema
from compiler.schema_generators.db_generator import generate_database_schema
from compiler.schema_generators.ui_generator import generate_ui_schema
from compiler.validator import validate_schemas


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _full_pipeline(tmp_path: Path):
    """Run the complete Phase 1→3 pipeline and return all schemas + architecture."""
    intent = extract_intent(
        "Build a CRM with contacts, dashboards, admin and user roles, Stripe payments, free and premium plans.",
        log_dir=tmp_path,
    )
    architecture = plan_architecture(intent, log_dir=tmp_path)
    app_spec = AppSpec(
        application_type=intent.application_type,
        entities=architecture.entities,
        pages=architecture.pages,
        business_rules=architecture.business_rules,
        integrations=architecture.integrations,
        assumptions=architecture.assumptions,
        clarification_questions=architecture.clarification_questions,
        source_intent_fields=("application_type", "entities", "pages", "roles"),
        rationale="Phase 4 test AppSpec mirrors the architecture contract boundary.",
    )
    ui = generate_ui_schema(architecture, app_spec, log_dir=tmp_path)
    api = generate_api_schema(architecture, app_spec, log_dir=tmp_path)
    db = generate_database_schema(architecture, app_spec, log_dir=tmp_path)
    auth = generate_auth_schema(architecture, app_spec, log_dir=tmp_path)
    return ui, api, db, auth, architecture


def _issues_with_code(report: ValidationReport, code: str):
    return [issue for issue in report.issues if issue.code == code]


# ---------------------------------------------------------------------------
# Core functionality
# ---------------------------------------------------------------------------


def test_validator_reports_valid_for_well_formed_pipeline(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    report = validate_schemas(ui, api, db, auth, architecture, log_dir=tmp_path)

    assert isinstance(report, ValidationReport)
    assert report.valid is True
    assert report.issues == ()
    assert set(report.layers_validated) == {"ui", "api", "db", "auth"}
    assert set(report.cross_layer_checks) == {"ui_api", "api_db", "auth_ui", "business_rules"}


def test_validator_is_deterministic(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    first = validate_schemas(ui, api, db, auth, architecture, log_dir=tmp_path)
    second = validate_schemas(ui, api, db, auth, architecture, log_dir=tmp_path)

    assert first == second
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_validator_writes_execution_log(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    validate_schemas(ui, api, db, auth, architecture, log_dir=tmp_path)
    log = read_stage_log(tmp_path / "validation.json")

    assert log.stage == CompilerStage.VALIDATION
    assert log.success_status is True
    assert log.validation_errors == ()


def test_validation_report_contract_round_trips(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    report = validate_schemas(ui, api, db, auth, architecture, log_dir=tmp_path)

    assert ValidationReport.model_validate(report.model_dump()) == report
    assert ValidationReport.model_validate(report.model_dump(mode="json")) == report


# ---------------------------------------------------------------------------
# UI ↔ API cross-layer checks
# ---------------------------------------------------------------------------


def test_validator_detects_form_without_matching_endpoint(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Add a form targeting a non-existent entity.
    ui_dict = ui.model_dump()
    ui_dict["forms"] = list(ui_dict["forms"]) + [
        {
            "id": "form_orphan",
            "page_route": "/orphans",
            "entity": "Orphan",
            "fields": ("name",),
            "submit_action": "create:Orphan",
            "source_intent_fields": ("entities",),
            "rationale": "Test form for an entity that has no API endpoint.",
        }
    ]
    modified_ui = UISchema.model_validate(ui_dict)

    report = validate_schemas(modified_ui, api, db, auth, architecture, log_dir=tmp_path)

    assert report.valid is False
    assert _issues_with_code(report, "FORM_MISSING_ENDPOINT")


def test_validator_detects_form_field_not_in_api_model(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Add a ghost field to the first form.
    ui_dict = ui.model_dump()
    first_form = ui_dict["forms"][0]
    first_form["fields"] = list(first_form["fields"]) + ["ghost_field"]
    modified_ui = UISchema.model_validate(ui_dict)

    report = validate_schemas(modified_ui, api, db, auth, architecture, log_dir=tmp_path)

    assert report.valid is False
    matching = _issues_with_code(report, "FORM_FIELD_NOT_IN_API")
    assert matching
    assert any("ghost_field" in issue.message for issue in matching)


# ---------------------------------------------------------------------------
# API ↔ DB cross-layer checks
# ---------------------------------------------------------------------------


def test_validator_detects_api_field_not_in_db(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Inject a field into the first request model that doesn't exist in the DB.
    api_dict = api.model_dump()
    first_model = api_dict["request_models"][0]
    first_model["fields"] = list(first_model["fields"]) + [
        {
            "name": "phantom_column",
            "field_type": "string",
            "required": False,
            "source_intent_fields": ("entities",),
            "rationale": "Injected for negative testing.",
        }
    ]
    modified_api = APISchema.model_validate(api_dict)

    report = validate_schemas(ui, modified_api, db, auth, architecture, log_dir=tmp_path)

    assert report.valid is False
    matching = _issues_with_code(report, "API_FIELD_NOT_IN_DB")
    assert matching
    assert any("phantom_column" in issue.message for issue in matching)


def test_validator_detects_type_mismatch_across_layers(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Change the type of 'name' field in the first request model.
    api_dict = api.model_dump()
    for field in api_dict["request_models"][0]["fields"]:
        if field["name"] == "name":
            field["field_type"] = "integer"
            break
    modified_api = APISchema.model_validate(api_dict)

    report = validate_schemas(ui, modified_api, db, auth, architecture, log_dir=tmp_path)

    assert report.valid is False
    matching = _issues_with_code(report, "TYPE_MISMATCH")
    assert matching
    assert any("name" in issue.message for issue in matching)


# ---------------------------------------------------------------------------
# Auth ↔ UI cross-layer checks
# ---------------------------------------------------------------------------


def test_validator_detects_ui_role_not_in_auth(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Remove all roles from auth schema.
    auth_dict = auth.model_dump()
    auth_dict["roles"] = ()
    auth_dict["permissions"] = ()
    auth_dict["access_policies"] = ()
    auth_dict["feature_gating"] = ()
    modified_auth = AuthSchema.model_validate(auth_dict)

    report = validate_schemas(ui, api, db, modified_auth, architecture, log_dir=tmp_path)

    assert report.valid is False
    assert _issues_with_code(report, "UI_ROLE_NOT_IN_AUTH")


def test_validator_detects_auth_route_not_in_ui(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Add an access policy with a non-existent route.
    auth_dict = auth.model_dump()
    auth_dict["access_policies"] = list(auth_dict["access_policies"]) + [
        {
            "role": auth_dict["roles"][0]["name"],
            "page_routes": ("/nonexistent_page",),
            "permissions": ("read:test",),
            "source_intent_fields": ("roles",),
            "rationale": "Test policy with orphan route.",
        }
    ]
    modified_auth = AuthSchema.model_validate(auth_dict)

    report = validate_schemas(ui, api, db, modified_auth, architecture, log_dir=tmp_path)

    assert report.valid is False
    matching = _issues_with_code(report, "AUTH_ROUTE_NOT_IN_UI")
    assert matching
    assert any("/nonexistent_page" in issue.message for issue in matching)


# ---------------------------------------------------------------------------
# Business rules ↔ All layers
# ---------------------------------------------------------------------------


def test_validator_detects_business_rule_entity_not_in_db(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Remove all tables from DB schema so business rule entities are orphaned.
    db_dict = db.model_dump()
    db_dict["tables"] = ()
    db_dict["fields"] = ()
    db_dict["constraints"] = ()
    db_dict["indexes"] = ()
    modified_db = DatabaseSchema.model_validate(db_dict)

    report = validate_schemas(ui, api, modified_db, auth, architecture, log_dir=tmp_path)

    assert report.valid is False
    assert _issues_with_code(report, "RULE_ENTITY_NOT_IN_DB")


def test_validator_detects_business_rule_role_not_in_auth(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Remove all roles from auth so business rule roles are orphaned.
    auth_dict = auth.model_dump()
    auth_dict["roles"] = ()
    auth_dict["permissions"] = ()
    auth_dict["access_policies"] = ()
    auth_dict["feature_gating"] = ()
    modified_auth = AuthSchema.model_validate(auth_dict)

    report = validate_schemas(ui, api, db, modified_auth, architecture, log_dir=tmp_path)

    assert report.valid is False
    assert _issues_with_code(report, "RULE_ROLE_NOT_IN_AUTH")


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------


def test_validator_detects_missing_required_fields(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Create an empty DB schema.
    empty_db = DatabaseSchema.model_validate({
        "tables": (),
        "fields": (),
        "relationships": (),
        "constraints": (),
        "indexes": (),
        "source_intent_fields": ("entities",),
        "rationale": "Empty DB for testing.",
    })

    report = validate_schemas(ui, api, empty_db, auth, architecture, log_dir=tmp_path)

    assert report.valid is False
    matching = _issues_with_code(report, "REQUIRED_FIELD_EMPTY")
    assert matching
    assert any("table" in issue.message.lower() for issue in matching)
