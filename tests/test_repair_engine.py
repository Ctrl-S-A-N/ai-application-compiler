"""Phase 5 – Targeted Repair Engine tests.

Comprehensive tests for deterministic, rule-based repairs.
Each test:
  1. Constructs a broken schema to trigger a specific validation issue.
  2. Validates → repairs → re-validates.
  3. Asserts only the affected layer changed.
  4. Asserts the repair resolved the validation issue.
"""

from pathlib import Path

from compiler.architecture_planner import plan_architecture
from compiler.contracts import (
    APISchema,
    AppSpec,
    AuthSchema,
    CompilerStage,
    DatabaseSchema,
    RepairLog,
    RepairTask,
    UISchema,
    ValidationReport,
)
from compiler.intent_extractor import extract_intent
from compiler.logging import read_stage_log
from compiler.repair_engine import execute_repairs, plan_repairs
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
        rationale="Phase 5 test AppSpec mirrors the architecture contract boundary.",
    )
    ui = generate_ui_schema(architecture, app_spec, log_dir=tmp_path)
    api = generate_api_schema(architecture, app_spec, log_dir=tmp_path)
    db = generate_database_schema(architecture, app_spec, log_dir=tmp_path)
    auth = generate_auth_schema(architecture, app_spec, log_dir=tmp_path)
    return ui, api, db, auth, architecture


def _break_and_repair(tmp_path, ui, api, db, auth, architecture):
    """Validate → plan → execute → return (repaired schemas, repair_log, pre-report)."""
    pre_report = validate_schemas(ui, api, db, auth, architecture, log_dir=tmp_path)
    task = plan_repairs(pre_report)
    r_ui, r_api, r_db, r_auth, log = execute_repairs(
        task, ui, api, db, auth, architecture, log_dir=tmp_path,
    )
    return r_ui, r_api, r_db, r_auth, log, pre_report


# ---------------------------------------------------------------------------
# Core repair engine tests
# ---------------------------------------------------------------------------


def test_repair_on_valid_pipeline_is_noop(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)
    report = validate_schemas(ui, api, db, auth, architecture, log_dir=tmp_path)

    task = plan_repairs(report)

    assert task.actions == ()
    assert task.source_validation_issues == 0


def test_repair_is_deterministic(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)
    # Inject a type mismatch.
    api_dict = api.model_dump()
    for field in api_dict["request_models"][0]["fields"]:
        if field["name"] == "name":
            field["field_type"] = "integer"
            break
    broken_api = APISchema.model_validate(api_dict)

    _, _, _, _, log1, _ = _break_and_repair(tmp_path, ui, broken_api, db, auth, architecture)
    _, _, _, _, log2, _ = _break_and_repair(tmp_path, ui, broken_api, db, auth, architecture)

    assert log1 == log2
    assert log1.model_dump(mode="json") == log2.model_dump(mode="json")


def test_repair_writes_execution_log(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)
    report = validate_schemas(ui, api, db, auth, architecture, log_dir=tmp_path)
    task = plan_repairs(report)

    execute_repairs(task, ui, api, db, auth, architecture, log_dir=tmp_path)
    log = read_stage_log(tmp_path / "repair.json")

    assert log.stage == CompilerStage.REPAIR
    assert log.success_status is True


def test_repair_log_contract_round_trips(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)
    report = validate_schemas(ui, api, db, auth, architecture, log_dir=tmp_path)
    task = plan_repairs(report)
    _, _, _, _, repair_log = execute_repairs(task, ui, api, db, auth, architecture, log_dir=tmp_path)

    assert RepairLog.model_validate(repair_log.model_dump()) == repair_log
    assert RepairLog.model_validate(repair_log.model_dump(mode="json")) == repair_log


def test_repair_task_contract_round_trips(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)
    report = validate_schemas(ui, api, db, auth, architecture, log_dir=tmp_path)
    task = plan_repairs(report)

    assert RepairTask.model_validate(task.model_dump()) == task


# ---------------------------------------------------------------------------
# DB field missing → repair DB schema only
# ---------------------------------------------------------------------------


def test_repair_adds_missing_db_field(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Inject a phantom field in the first API request model.
    api_dict = api.model_dump()
    api_dict["request_models"][0]["fields"] = list(api_dict["request_models"][0]["fields"]) + [{
        "name": "phantom_column", "field_type": "string", "required": False,
        "source_intent_fields": ("entities",), "rationale": "Injected for repair test.",
    }]
    broken_api = APISchema.model_validate(api_dict)

    r_ui, r_api, r_db, r_auth, repair_log, pre_report = _break_and_repair(
        tmp_path, ui, broken_api, db, auth, architecture,
    )

    # DB was repaired.
    assert r_db != db
    assert any(r.success and r.affected_layer == "db" for r in repair_log.results)
    # Unrelated layers untouched.
    assert r_ui == ui
    assert r_auth == auth
    # The phantom field now exists in the repaired DB.
    entity_name = _extract_entity_name(api_dict["request_models"][0]["name"])
    db_fields = set()
    for table in r_db.tables:
        if table.entity == entity_name:
            db_fields = {f.name for f in table.fields}
    assert "phantom_column" in db_fields


def test_repair_adds_stub_db_table_for_business_rule(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Empty the DB to orphan business rule entities.
    empty_db = DatabaseSchema.model_validate({
        "tables": (), "fields": (), "relationships": (), "constraints": (), "indexes": (),
        "source_intent_fields": ("entities",), "rationale": "Empty DB for repair test.",
    })

    r_ui, r_api, r_db, r_auth, repair_log, _ = _break_and_repair(
        tmp_path, ui, api, empty_db, auth, architecture,
    )

    # Stub tables were added.
    assert r_db != empty_db
    assert r_db.tables  # No longer empty.
    assert any(r.success and r.repair_action == "add_db_table_stub" for r in repair_log.results)
    # Unrelated layers untouched.
    assert r_ui == ui
    assert r_auth == auth


# ---------------------------------------------------------------------------
# API references unknown field → repair API schema only
# ---------------------------------------------------------------------------


def test_repair_fixes_api_type_mismatch(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Change the type of 'name' field in the first request model.
    api_dict = api.model_dump()
    for field in api_dict["request_models"][0]["fields"]:
        if field["name"] == "name":
            field["field_type"] = "integer"
            break
    broken_api = APISchema.model_validate(api_dict)

    r_ui, r_api, r_db, r_auth, repair_log, _ = _break_and_repair(
        tmp_path, ui, broken_api, db, auth, architecture,
    )

    # API was repaired.
    assert r_api != broken_api
    assert any(r.success and r.affected_layer == "api" for r in repair_log.results)
    # The name field should now have the correct type (string, matching DB).
    repaired_model = r_api.request_models[0]
    name_field = next(f for f in repaired_model.fields if f.name == "name")
    assert name_field.field_type == "string"
    # Unrelated layers untouched.
    assert r_ui == ui
    assert r_db == db
    assert r_auth == auth


# ---------------------------------------------------------------------------
# UI references missing endpoint → repair UI schema only
# ---------------------------------------------------------------------------


def test_repair_removes_orphan_form(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Add a form for a non-existent entity.
    ui_dict = ui.model_dump()
    ui_dict["forms"] = list(ui_dict["forms"]) + [{
        "id": "form_orphan", "page_route": "/orphans", "entity": "Orphan",
        "fields": ("name",), "submit_action": "create:Orphan",
        "source_intent_fields": ("entities",),
        "rationale": "Orphan form for repair test.",
    }]
    broken_ui = UISchema.model_validate(ui_dict)

    r_ui, r_api, r_db, r_auth, repair_log, _ = _break_and_repair(
        tmp_path, broken_ui, api, db, auth, architecture,
    )

    # UI was repaired — orphan form removed.
    assert r_ui != broken_ui
    assert all(f.id != "form_orphan" for f in r_ui.forms)
    assert any(r.success and r.affected_layer == "ui" for r in repair_log.results)
    # Unrelated layers untouched.
    assert r_api == api
    assert r_db == db
    assert r_auth == auth


def test_repair_removes_orphan_form_field(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Add a ghost field to the first form.
    ui_dict = ui.model_dump()
    first_form = ui_dict["forms"][0]
    first_form["fields"] = list(first_form["fields"]) + ["ghost_field"]
    broken_ui = UISchema.model_validate(ui_dict)

    r_ui, r_api, r_db, r_auth, repair_log, _ = _break_and_repair(
        tmp_path, broken_ui, api, db, auth, architecture,
    )

    # UI was repaired — ghost field removed.
    assert r_ui != broken_ui
    repaired_form = next(f for f in r_ui.forms if f.id == first_form["id"])
    assert "ghost_field" not in repaired_form.fields
    assert any(r.success and r.affected_layer == "ui" for r in repair_log.results)
    # Unrelated layers untouched.
    assert r_api == api
    assert r_db == db
    assert r_auth == auth


# ---------------------------------------------------------------------------
# Auth references missing permission → repair Auth schema only
# ---------------------------------------------------------------------------


def test_repair_adds_missing_auth_role(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Remove all roles from auth schema.
    auth_dict = auth.model_dump()
    auth_dict["roles"] = ()
    auth_dict["permissions"] = ()
    auth_dict["access_policies"] = ()
    auth_dict["feature_gating"] = ()
    broken_auth = AuthSchema.model_validate(auth_dict)

    r_ui, r_api, r_db, r_auth, repair_log, _ = _break_and_repair(
        tmp_path, ui, api, db, broken_auth, architecture,
    )

    # Auth was repaired — roles added back.
    assert r_auth != broken_auth
    assert r_auth.roles  # No longer empty.
    assert any(r.success and r.affected_layer == "auth" for r in repair_log.results)
    # Unrelated layers untouched.
    assert r_ui == ui
    assert r_db == db


def test_repair_removes_orphan_auth_route(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Add an access policy with a non-existent route.
    auth_dict = auth.model_dump()
    auth_dict["access_policies"] = list(auth_dict["access_policies"]) + [{
        "role": auth_dict["roles"][0]["name"],
        "page_routes": ("/nonexistent_page",),
        "permissions": ("read:test",),
        "source_intent_fields": ("roles",),
        "rationale": "Test policy with orphan route.",
    }]
    broken_auth = AuthSchema.model_validate(auth_dict)

    r_ui, r_api, r_db, r_auth, repair_log, _ = _break_and_repair(
        tmp_path, ui, api, db, broken_auth, architecture,
    )

    # Auth was repaired — orphan route removed.
    assert r_auth != broken_auth
    for policy in r_auth.access_policies:
        assert "/nonexistent_page" not in policy.page_routes
    assert any(r.success and r.affected_layer == "auth" for r in repair_log.results)
    # Unrelated layers untouched.
    assert r_ui == ui
    assert r_db == db


# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------


def test_repair_ignores_warnings(tmp_path: Path) -> None:
    from compiler.contracts import ValidationIssue, ValidationSeverity, ValidationReport
    report = ValidationReport(
        valid=True,
        issues=(ValidationIssue(
            severity=ValidationSeverity.WARNING,
            layer="ui",
            code="SOME_WARNING",
            message="A warning message."
        ),)
    )
    task = plan_repairs(report)
    assert task.actions == ()


def test_repair_unknown_handler(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)
    from compiler.contracts import RepairAction
    task = RepairTask(
        source_validation_issues=1,
        actions=(RepairAction(
            error_code="FAKE_ERROR",
            affected_layer="ui",
            repair_action="fake_handler_action"
        ),)
    )
    r_ui, r_api, r_db, r_auth, log = execute_repairs(task, ui, api, db, auth, architecture, log_dir=tmp_path)
    assert len(log.results) == 1
    assert log.results[0].success is False
    assert "No handler" in log.results[0].detail


def test_repair_post_repair_validation_failure(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)
    # Break the DB schema
    db_dict = db.model_dump()
    db_dict["tables"] = ()
    broken_db = DatabaseSchema.model_validate(db_dict)
    
    task = RepairTask(source_validation_issues=1, actions=())
    
    r_ui, r_api, r_db, r_auth, log = execute_repairs(task, ui, api, broken_db, auth, architecture, log_dir=tmp_path)
    assert log.revalidation_passed is False
    
    exec_log = read_stage_log(tmp_path / "repair.json")
    assert exec_log.success_status is False
    assert any("Post-repair" in err for err in exec_log.validation_errors)


def test_repair_exception_during_execution(tmp_path: Path) -> None:
    task = RepairTask(source_validation_issues=1, actions=())
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)
    import pytest
    with pytest.raises(Exception):
        execute_repairs(task, None, api, db, auth, architecture, log_dir=tmp_path)  # type: ignore
    exec_log = read_stage_log(tmp_path / "repair.json")
    assert exec_log.success_status is False


def test_repair_removes_component_binding(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)
    ui_dict = ui.model_dump()
    ui_dict["components"] = list(ui_dict["components"]) + [{
        "id": "comp1", "component_type": "table", "page_route": "/",
        "bound_entity": "UnknownEntity", "bound_fields": (),
        "source_intent_fields": ("entities",), "rationale": "test"
    }]
    broken_ui = UISchema.model_validate(ui_dict)
    r_ui, r_api, r_db, r_auth, repair_log, _ = _break_and_repair(tmp_path, broken_ui, api, db, auth, architecture)
    assert any(r.repair_action == "remove_component_binding" and r.success for r in repair_log.results)
    repaired_comp = next(c for c in r_ui.components if c.id == "comp1")
    assert repaired_comp.bound_entity is None


def test_repair_removes_component_field(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)
    ui_dict = ui.model_dump()
    ui_dict["components"] = list(ui_dict["components"]) + [{
        "id": "comp2", "component_type": "table", "page_route": "/",
        "bound_entity": architecture.entities[0].name, "bound_fields": ("ghost_field",),
        "source_intent_fields": ("entities",), "rationale": "test"
    }]
    broken_ui = UISchema.model_validate(ui_dict)
    r_ui, r_api, r_db, r_auth, repair_log, _ = _break_and_repair(tmp_path, broken_ui, api, db, auth, architecture)
    assert any(r.repair_action == "remove_component_field" and r.success for r in repair_log.results)
    repaired_comp = next(c for c in r_ui.components if c.id == "comp2")
    assert "ghost_field" not in repaired_comp.bound_fields


def test_repair_adds_auth_role_for_business_rule(tmp_path: Path) -> None:
    from compiler.contracts import ArchitectureManifest
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)
    auth_dict = auth.model_dump()
    auth_dict["roles"] = ()
    broken_auth = AuthSchema.model_validate(auth_dict)
    
    arch_dict = architecture.model_dump()
    arch_dict["business_rules"] = list(arch_dict["business_rules"]) + [{
        "id": "br1", "description": "test", "applies_to": (),
        "referenced_entities": (), "referenced_roles": (architecture.roles[0].name,),
        "source_intent_fields": ("roles",), "rationale": "test"
    }]
    mod_arch = ArchitectureManifest.model_validate(arch_dict)
    
    r_ui, r_api, r_db, r_auth, repair_log, pre = _break_and_repair(tmp_path, ui, api, db, broken_auth, mod_arch)
    assert any(i.code == "RULE_ROLE_NOT_IN_AUTH" for i in pre.issues)
    assert any(r.repair_action == "add_auth_role" and r.success for r in repair_log.results)
    assert len(r_auth.roles) > 0


def test_repair_handles_malformed_source_refs(tmp_path: Path) -> None:
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)
    from compiler.contracts import RepairAction
    actions = [
        RepairAction(error_code="E1", affected_layer="ui", repair_action="remove_orphan_form_field", source_ref="bad"),
        RepairAction(error_code="E2", affected_layer="ui", repair_action="remove_component_field", source_ref="bad"),
        RepairAction(error_code="E3", affected_layer="db", repair_action="add_db_field", source_ref="bad"),
        RepairAction(error_code="E4", affected_layer="api", repair_action="fix_api_field_type", source_ref="bad"),
        RepairAction(error_code="E5", affected_layer="db", repair_action="add_db_field", source_ref="UnknownModel.field"),
        RepairAction(error_code="E6", affected_layer="api", repair_action="fix_api_field_type", source_ref=f"{api.request_models[0].name}.unknown_field"),
    ]
    task = RepairTask(source_validation_issues=len(actions), actions=tuple(actions))
    r_ui, r_api, r_db, r_auth, log = execute_repairs(task, ui, api, db, auth, architecture, log_dir=tmp_path)
    for res in log.results:
        assert res.success is False


# ---------------------------------------------------------------------------
# Revalidation
# ---------------------------------------------------------------------------


def test_repair_resolves_validation_issues(tmp_path: Path) -> None:
    """After repair, the repaired schemas must pass re-validation."""
    ui, api, db, auth, architecture = _full_pipeline(tmp_path)

    # Introduce a type mismatch.
    api_dict = api.model_dump()
    for field in api_dict["request_models"][0]["fields"]:
        if field["name"] == "name":
            field["field_type"] = "integer"
            break
    broken_api = APISchema.model_validate(api_dict)

    r_ui, r_api, r_db, r_auth, repair_log, _ = _break_and_repair(
        tmp_path, ui, broken_api, db, auth, architecture,
    )

    # Explicitly re-validate the repaired schemas.
    post_report = validate_schemas(r_ui, r_api, r_db, r_auth, architecture, log_dir=tmp_path)
    assert post_report.valid is True
    assert repair_log.revalidation_passed is True


# ---------------------------------------------------------------------------
# Helper shared with tests
# ---------------------------------------------------------------------------


def _extract_entity_name(model_name: str) -> str | None:
    for suffix in ("Request", "Response"):
        if model_name.endswith(suffix):
            return model_name[: -len(suffix)]
    return None
