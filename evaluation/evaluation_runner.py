"""Phase 8 – Evaluation Framework Runner.

Automated runner for the compiler pipeline.
Evaluates dataset prompts, measuring success rate, repairs, validation, latency, and clarifications.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from compiler.architecture_planner import plan_architecture
from compiler.contracts import AppSpec, ValidationSeverity
from compiler.intent_extractor import extract_intent
from compiler.repair_engine import execute_repairs, plan_repairs
from compiler.runtime_generator import generate_runtime
from compiler.schema_generators.api_generator import generate_api_schema
from compiler.schema_generators.auth_generator import generate_auth_schema
from compiler.schema_generators.db_generator import generate_database_schema
from compiler.schema_generators.ui_generator import generate_ui_schema
from compiler.validator import validate_schemas


def run_evaluation(dataset_path: Path, output_dir: Path) -> dict[str, Any]:
    """Run evaluation on dataset and save report."""
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    
    prompts = dataset.get("realistic", []) + dataset.get("edge_cases", [])
    
    results = []
    
    for item in prompts:
        prompt_id = item["id"]
        prompt_text = item["prompt"]
        
        start_time = time.perf_counter()
        
        prompt_log_dir = output_dir / "logs" / prompt_id
        prompt_log_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Phase 2: Extractor & Planner
            intent = extract_intent(prompt_text, log_dir=prompt_log_dir)
            architecture = plan_architecture(intent, log_dir=prompt_log_dir)
            
            app_spec = AppSpec(
                application_type=intent.application_type,
                entities=architecture.entities,
                pages=architecture.pages,
                business_rules=architecture.business_rules,
                integrations=architecture.integrations,
                assumptions=architecture.assumptions,
                clarification_questions=architecture.clarification_questions,
                source_intent_fields=("application_type",),
                rationale="AppSpec boundary for evaluation."
            )
            
            # Phase 3: Generators
            ui = generate_ui_schema(architecture, app_spec, log_dir=prompt_log_dir)
            api = generate_api_schema(architecture, app_spec, log_dir=prompt_log_dir)
            db = generate_database_schema(architecture, app_spec, log_dir=prompt_log_dir)
            auth = generate_auth_schema(architecture, app_spec, log_dir=prompt_log_dir)
            
            # Phase 4: Validation
            report = validate_schemas(ui, api, db, auth, architecture, log_dir=prompt_log_dir)
            
            validation_failures = sum(1 for i in report.issues if i.severity == ValidationSeverity.ERROR)
            
            # Phase 5: Repair
            repair_count = 0
            if not report.valid:
                task = plan_repairs(report)
                ui, api, db, auth, repair_log = execute_repairs(task, ui, api, db, auth, architecture, log_dir=prompt_log_dir)
                repair_count = repair_log.issues_repaired
                is_valid = repair_log.revalidation_passed
            else:
                is_valid = True
                
            # Phase 6: Runtime Generation
            runtime_success = False
            if is_valid:
                runtime_dir = output_dir / "runtimes" / prompt_id
                runtime_report = generate_runtime(app_spec, ui, api, db, auth, architecture, runtime_dir, log_dir=prompt_log_dir)
                runtime_success = runtime_report.success
                
            end_time = time.perf_counter()
            latency_ms = (end_time - start_time) * 1000
            
            clarifications = len(intent.clarification_questions) + len(architecture.clarification_questions)
            
            results.append({
                "id": prompt_id,
                "success": runtime_success,
                "validation_failures": validation_failures,
                "repair_count": repair_count,
                "latency_ms": latency_ms,
                "clarification_requests": clarifications,
                "error": None
            })
            
        except Exception as e:
            end_time = time.perf_counter()
            results.append({
                "id": prompt_id,
                "success": False,
                "validation_failures": 0,
                "repair_count": 0,
                "latency_ms": (end_time - start_time) * 1000,
                "clarification_requests": 0,
                "error": str(e)
            })

    # Aggregate
    total = len(results)
    successes = sum(1 for r in results if r["success"])
    
    report_data = {
        "summary": {
            "total_prompts": total,
            "success_rate": successes / total if total > 0 else 0.0,
            "total_repairs": sum(r["repair_count"] for r in results),
            "total_validation_failures": sum(r["validation_failures"] for r in results),
            "total_clarification_requests": sum(r["clarification_requests"] for r in results),
            "avg_latency_ms": sum(r["latency_ms"] for r in results) / total if total > 0 else 0.0
        },
        "results": results
    }
    
    report_path = output_dir / "evaluation_report.json"
    report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    
    return report_data

if __name__ == "__main__":
    base_dir = Path(__file__).parent
    run_evaluation(base_dir / "dataset.json", base_dir)
