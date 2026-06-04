"""Phase 6 – Runtime Generator tests.

Comprehensive tests for deterministic, template-based generation.
"""

from pathlib import Path

from compiler.architecture_planner import plan_architecture
from compiler.contracts import (
    APISchema,
    AppSpec,
    AuthSchema,
    DatabaseSchema,
    FieldType,
    RuntimeGenerationReport,
    UISchema,
)
from compiler.intent_extractor import extract_intent
from compiler.runtime_generator import generate_runtime
from compiler.schema_generators.api_generator import generate_api_schema
from compiler.schema_generators.auth_generator import generate_auth_schema
from compiler.schema_generators.db_generator import generate_database_schema
from compiler.schema_generators.ui_generator import generate_ui_schema


def _full_pipeline(tmp_path: Path):
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
        source_intent_fields=("application_type",),
        rationale="test",
    )
    ui = generate_ui_schema(architecture, app_spec, log_dir=tmp_path)
    api = generate_api_schema(architecture, app_spec, log_dir=tmp_path)
    db = generate_database_schema(architecture, app_spec, log_dir=tmp_path)
    auth = generate_auth_schema(architecture, app_spec, log_dir=tmp_path)
    return ui, api, db, auth, architecture, app_spec


def test_runtime_generation_success(tmp_path: Path) -> None:
    ui, api, db, auth, arch, spec = _full_pipeline(tmp_path)
    output_dir = tmp_path / "generated_app"
    
    report = generate_runtime(spec, ui, api, db, auth, arch, output_dir, log_dir=tmp_path)
    
    assert report.success is True
    assert report.backend_routes_compiled is True
    assert report.database_schema_valid is True
    assert report.frontend_artifacts_produced is True
    assert len(report.generated_files) == 4
    
    assert (output_dir / "backend" / "main.py").exists()
    assert (output_dir / "database" / "schema.sql").exists()
    assert (output_dir / "frontend" / "index.html").exists()
    assert (output_dir / "backend" / "auth_config.json").exists()


def test_runtime_generation_deterministic(tmp_path: Path) -> None:
    ui, api, db, auth, arch, spec = _full_pipeline(tmp_path)
    
    dir1 = tmp_path / "gen1"
    dir2 = tmp_path / "gen2"
    
    report1 = generate_runtime(spec, ui, api, db, auth, arch, dir1, log_dir=tmp_path)
    report2 = generate_runtime(spec, ui, api, db, auth, arch, dir2, log_dir=tmp_path)
    
    assert report1.success is True
    assert report2.success is True
    
    content1 = (dir1 / "backend" / "main.py").read_text(encoding="utf-8")
    content2 = (dir2 / "backend" / "main.py").read_text(encoding="utf-8")
    assert content1 == content2
    
    sql1 = (dir1 / "database" / "schema.sql").read_text(encoding="utf-8")
    sql2 = (dir2 / "database" / "schema.sql").read_text(encoding="utf-8")
    assert sql1 == sql2


def test_runtime_generation_invalid_sql(tmp_path: Path) -> None:
    ui, api, db, auth, arch, spec = _full_pipeline(tmp_path)
    
    # Intentionally corrupt the DB schema to produce bad SQL
    db_dict = db.model_dump()
    db_dict["tables"][0]["name"] = "Invalid Name With Spaces"
    broken_db = DatabaseSchema.model_validate(db_dict)
    
    output_dir = tmp_path / "generated_bad_sql"
    report = generate_runtime(spec, ui, api, broken_db, auth, arch, output_dir, log_dir=tmp_path)
    
    assert report.success is False
    assert report.database_schema_valid is False
    assert report.backend_routes_compiled is True


def test_runtime_generation_invalid_python(tmp_path: Path) -> None:
    ui, api, db, auth, arch, spec = _full_pipeline(tmp_path)
    
    # Intentionally corrupt the API schema to produce bad Python
    api_dict = api.model_dump()
    api_dict["request_models"][0]["name"] = "class " # Causes "class class (...):" which is a SyntaxError
    broken_api = APISchema.model_validate(api_dict)
    
    output_dir = tmp_path / "generated_bad_py"
    report = generate_runtime(spec, ui, broken_api, db, auth, arch, output_dir, log_dir=tmp_path)
    
    assert report.success is False
    assert report.backend_routes_compiled is False


def test_runtime_generation_exception_handling(tmp_path: Path) -> None:
    import pytest
    ui, api, db, auth, arch, spec = _full_pipeline(tmp_path)
    
    # Pass a file instead of a directory to cause PermissionError/NotADirectoryError
    output_dir = tmp_path / "bad_dir"
    output_dir.write_text("not a dir")
    
    with pytest.raises(Exception):
        generate_runtime(spec, ui, api, db, auth, arch, output_dir, log_dir=tmp_path)
