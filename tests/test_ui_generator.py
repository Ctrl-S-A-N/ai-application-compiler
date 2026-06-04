from pathlib import Path

from compiler.architecture_planner import plan_architecture
from compiler.contracts import AppSpec, CompilerStage, UISchema
from compiler.intent_extractor import extract_intent
from compiler.logging import read_stage_log
from compiler.schema_generators.ui_generator import generate_ui_schema


def test_ui_generator_outputs_contract_sections(tmp_path: Path) -> None:
    architecture, app_spec = _inputs(tmp_path)

    schema = generate_ui_schema(architecture, app_spec, log_dir=tmp_path)

    assert isinstance(schema, UISchema)
    assert schema.pages
    assert schema.layouts
    assert schema.components
    assert schema.forms
    assert schema.navigation
    assert schema.role_visibility
    assert all(page.role_visibility for page in schema.pages)
    assert UISchema.model_validate(schema.model_dump()) == schema


def test_ui_generator_is_deterministic(tmp_path: Path) -> None:
    architecture, app_spec = _inputs(tmp_path)

    first = generate_ui_schema(architecture, app_spec, log_dir=tmp_path)
    second = generate_ui_schema(architecture, app_spec, log_dir=tmp_path)

    assert first == second
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_ui_generator_writes_execution_log(tmp_path: Path) -> None:
    architecture, app_spec = _inputs(tmp_path)

    generate_ui_schema(architecture, app_spec, log_dir=tmp_path)
    log = read_stage_log(tmp_path / "ui_schema_generation.json")

    assert log.stage == CompilerStage.UI_SCHEMA_GENERATION
    assert log.success_status is True


def _inputs(tmp_path: Path):
    intent = extract_intent(
        "Build a CRM with contacts, dashboards, admin and user roles, Stripe payments.",
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
        source_intent_fields=("application_type", "entities", "pages"),
        rationale="Phase 3 test AppSpec mirrors the architecture contract boundary.",
    )
    return architecture, app_spec

