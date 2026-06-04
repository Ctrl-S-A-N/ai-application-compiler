from fastapi import FastAPI

from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import tempfile

from compiler.intent_extractor import extract_intent
from compiler.architecture_planner import plan_architecture
from compiler.contracts import AppSpec
from compiler.schema_generators.ui_generator import generate_ui_schema
from compiler.schema_generators.api_generator import generate_api_schema
from compiler.schema_generators.db_generator import generate_database_schema
from compiler.schema_generators.auth_generator import generate_auth_schema
from compiler.validator import validate_schemas
from compiler.repair_engine import plan_repairs, execute_repairs
from compiler.runtime_generator import generate_runtime


app = FastAPI(
    title="AI Application Compiler",
    version="0.1.0",
    description="Phase 1 foundation for deterministic application compilation.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CompileRequest(BaseModel):
    prompt: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/compile")
def compile_pipeline(request: CompileRequest):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        log_dir = tmp_path / "logs"
        log_dir.mkdir(exist_ok=True)
        
        # 1. Intent Extraction
        intent = extract_intent(request.prompt, log_dir=log_dir)
        
        # 2. Architecture Planning
        architecture = plan_architecture(intent, log_dir=log_dir)
        
        app_spec = AppSpec(
            application_type=intent.application_type,
            entities=architecture.entities,
            pages=architecture.pages,
            business_rules=architecture.business_rules,
            integrations=architecture.integrations,
            assumptions=architecture.assumptions,
            clarification_questions=architecture.clarification_questions,
            source_intent_fields=("application_type",),
            rationale="Compiler pipeline UI execution."
        )
        
        # 3. Schema Generation
        ui = generate_ui_schema(architecture, app_spec, log_dir=log_dir)
        api = generate_api_schema(architecture, app_spec, log_dir=log_dir)
        db = generate_database_schema(architecture, app_spec, log_dir=log_dir)
        auth = generate_auth_schema(architecture, app_spec, log_dir=log_dir)
        
        # 4. Validation
        validation_report = validate_schemas(ui, api, db, auth, architecture, log_dir=log_dir)
        
        # 5. Repair
        repair_report_dict = None
        if not validation_report.valid:
            task = plan_repairs(validation_report)
            ui, api, db, auth, repair_log = execute_repairs(task, ui, api, db, auth, architecture, log_dir=log_dir)
            repair_report_dict = repair_log.model_dump()
            is_valid = repair_log.revalidation_passed
        else:
            is_valid = True
            
        # 6. Runtime Generation
        runtime_report_dict = None
        if is_valid:
            runtime_dir = tmp_path / "generated"
            runtime_report = generate_runtime(app_spec, ui, api, db, auth, architecture, runtime_dir, log_dir=log_dir)
            runtime_report_dict = runtime_report.model_dump()
            
        return {
            "intent_ir": intent.model_dump(),
            "architecture": architecture.model_dump(),
            "ui_schema": ui.model_dump(),
            "api_schema": api.model_dump(),
            "db_schema": db.model_dump(),
            "auth_schema": auth.model_dump(),
            "validation_report": validation_report.model_dump(),
            "repair_report": repair_report_dict,
            "runtime_report": runtime_report_dict
        }
