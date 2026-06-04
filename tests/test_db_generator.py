from pathlib import Path

from compiler.architecture_planner import plan_architecture
from compiler.contracts import AppSpec, CompilerStage, DatabaseSchema
from compiler.intent_extractor import extract_intent
from compiler.logging import read_stage_log
from compiler.schema_generators.db_generator import generate_database_schema


def test_database_generator_outputs_contract_sections(tmp_path: Path) -> None:
    architecture, app_spec = _inputs(tmp_path)

    schema = generate_database_schema(architecture, app_spec, log_dir=tmp_path)

    assert isinstance(schema, DatabaseSchema)
    assert schema.tables
    assert schema.fields
    assert schema.constraints
    assert schema.indexes
    assert all(table.fields for table in schema.tables)
    assert DatabaseSchema.model_validate(schema.model_dump()) == schema


def test_database_generator_is_deterministic(tmp_path: Path) -> None:
    architecture, app_spec = _inputs(tmp_path)

    first = generate_database_schema(architecture, app_spec, log_dir=tmp_path)
    second = generate_database_schema(architecture, app_spec, log_dir=tmp_path)

    assert first == second
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_database_generator_writes_execution_log(tmp_path: Path) -> None:
    architecture, app_spec = _inputs(tmp_path)

    generate_database_schema(architecture, app_spec, log_dir=tmp_path)
    log = read_stage_log(tmp_path / "db_schema_generation.json")

    assert log.stage == CompilerStage.DB_SCHEMA_GENERATION
    assert log.success_status is True


def _inputs(tmp_path: Path):
    intent = extract_intent(
        "Build a CRM with contacts, accounts, dashboards, admin and user roles.",
        log_dir=tmp_path,
    )
    architecture = plan_architecture(intent, log_dir=tmp_path)
    app_spec = AppSpec(
        application_type=intent.application_type,
        entities=architecture.entities,
        pages=architecture.pages,
        business_rules=architecture.business_rules,
        source_intent_fields=("application_type", "entities"),
        rationale="Phase 3 test AppSpec mirrors the architecture contract boundary.",
    )
    return architecture, app_spec

