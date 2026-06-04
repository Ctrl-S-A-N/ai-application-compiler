"""Phase 6 – Runtime Generator.

Converts validated specifications into runnable application artifacts.
Pure template-based generation, deterministic, and no LLM calls.
"""

from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path

from compiler.contracts import (
    APISchema,
    AppSpec,
    ArchitectureManifest,
    AuthSchema,
    CompilerStage,
    DatabaseSchema,
    FieldType,
    RuntimeGenerationReport,
    UISchema,
)
from compiler.logging import DEFAULT_LOG_DIR, stage_execution


def generate_runtime(
    app_spec: AppSpec,
    ui_schema: UISchema,
    api_schema: APISchema,
    db_schema: DatabaseSchema,
    auth_schema: AuthSchema,
    architecture: ArchitectureManifest,
    output_dir: Path,
    log_dir: Path = DEFAULT_LOG_DIR,
) -> RuntimeGenerationReport:
    """Generate runtime artifacts from validated schemas."""
    with stage_execution(
        CompilerStage.RUNTIME_GENERATION,
        log_dir=log_dir,
    ) as validation_errors:
        
        try:
            # 1. Setup Directories
            output_dir.mkdir(parents=True, exist_ok=True)
            
            backend_dir = output_dir / "backend"
            frontend_dir = output_dir / "frontend"
            database_dir = output_dir / "database"
            
            for d in (backend_dir, frontend_dir, database_dir):
                d.mkdir(parents=True, exist_ok=True)
                
            generated_files: list[str] = []

            # 2. Database Generation (SQLite Schema)
            schema_sql = _generate_sqlite_schema(db_schema)
            schema_path = database_dir / "schema.sql"
            schema_path.write_text(schema_sql, encoding="utf-8")
            generated_files.append(str(schema_path))
            
            # 3. Backend Generation (FastAPI routes and models)
            backend_py = _generate_backend_fastapi(api_schema, auth_schema)
            backend_path = backend_dir / "main.py"
            backend_path.write_text(backend_py, encoding="utf-8")
            generated_files.append(str(backend_path))
            
            # 4. Frontend Generation (Minimal Pages)
            frontend_html = _generate_frontend_html(ui_schema)
            frontend_path = frontend_dir / "index.html"
            frontend_path.write_text(frontend_html, encoding="utf-8")
            generated_files.append(str(frontend_path))
            
            # 5. Auth Mapping (JSON config)
            auth_json = _generate_auth_mapping(auth_schema)
            auth_path = backend_dir / "auth_config.json"
            auth_path.write_text(auth_json, encoding="utf-8")
            generated_files.append(str(auth_path))

            # 6. Verification
            backend_routes_compiled = _verify_python_syntax(backend_path)
            database_schema_valid = _verify_sqlite_schema(schema_path)
            frontend_artifacts_produced = frontend_path.exists() and len(frontend_html.strip()) > 0
            
            if not backend_routes_compiled:
                validation_errors.append("Backend FastAPI routes failed to compile (syntax error).")
            if not database_schema_valid:
                validation_errors.append("Database SQLite schema is invalid.")

            success = backend_routes_compiled and database_schema_valid and frontend_artifacts_produced

            return RuntimeGenerationReport(
                success=success,
                generated_files=tuple(generated_files),
                backend_routes_compiled=backend_routes_compiled,
                database_schema_valid=database_schema_valid,
                frontend_artifacts_produced=frontend_artifacts_produced,
                details="Runtime generation completed." if success else "Runtime generation failed validation.",
            )

        except Exception as exc:
            validation_errors.append(str(exc))
            raise


def _generate_sqlite_schema(db: DatabaseSchema) -> str:
    """Generate SQLite schema from DatabaseSchema."""
    lines: list[str] = []
    
    # Map FieldType to SQLite types
    type_map = {
        FieldType.STRING: "TEXT",
        FieldType.TEXT: "TEXT",
        FieldType.INTEGER: "INTEGER",
        FieldType.FLOAT: "REAL",
        FieldType.BOOLEAN: "INTEGER",
        FieldType.DATETIME: "TEXT",
        FieldType.DATE: "TEXT",
        FieldType.UUID: "TEXT",
        FieldType.EMAIL: "TEXT",
    }
    
    for table in db.tables:
        lines.append(f"CREATE TABLE {table.name} (")
        field_defs = []
        for field in table.fields:
            sql_type = type_map.get(field.field_type, "TEXT")
            nullable = "" if field.nullable else " NOT NULL"
            unique = " UNIQUE" if field.unique else ""
            
            # Handle constraints
            pk = ""
            for c in db.constraints:
                if c.table == table.name and c.constraint_type == "primary_key" and field.name in c.fields:
                    pk = " PRIMARY KEY"
                    
            field_defs.append(f"    {field.name} {sql_type}{pk}{nullable}{unique}")
            
        # Add foreign keys if any
        for rel in db.relationships:
            if rel.from_table == table.name:
                field_defs.append(f"    FOREIGN KEY ({rel.to_table}_id) REFERENCES {rel.to_table}(id)")
                
        lines.append(",\n".join(field_defs))
        lines.append(");")
        lines.append("")
        
    for index in db.indexes:
        unique = "UNIQUE " if index.unique else ""
        idx_name = f"idx_{index.table}_{'_'.join(index.fields)}"
        fields = ", ".join(index.fields)
        lines.append(f"CREATE {unique}INDEX {idx_name} ON {index.table} ({fields});")
        
    return "\n".join(lines)


def _generate_backend_fastapi(api: APISchema, auth: AuthSchema) -> str:
    """Generate minimal FastAPI app with Pydantic models and routes."""
    lines: list[str] = [
        "from fastapi import FastAPI, Depends, HTTPException",
        "from pydantic import BaseModel",
        "from typing import Optional, List, Dict, Any",
        "import json",
        "",
        "app = FastAPI()",
        "",
        "# Models",
    ]
    
    # Type mapping to Python types
    py_type_map = {
        FieldType.STRING: "str",
        FieldType.TEXT: "str",
        FieldType.INTEGER: "int",
        FieldType.FLOAT: "float",
        FieldType.BOOLEAN: "bool",
        FieldType.DATETIME: "str",
        FieldType.DATE: "str",
        FieldType.UUID: "str",
        FieldType.EMAIL: "str",
    }

    # Generate Pydantic Models
    for model in sorted(list(api.request_models) + list(api.response_models), key=lambda m: m.name):
        lines.append(f"class {model.name}(BaseModel):")
        if not model.fields:
            lines.append("    pass")
        for field in model.fields:
            py_type = py_type_map.get(field.field_type, "str")
            if not field.required:
                py_type = f"Optional[{py_type}]"
                default = " = None"
            else:
                default = ""
            lines.append(f"    {field.name}: {py_type}{default}")
        lines.append("")

    lines.append("# Auth Dependency Stub")
    lines.append("def check_permissions(required_permission: str):")
    lines.append("    def _check(user: dict = Depends(lambda: {'role': 'admin'})):")
    lines.append("        pass")
    lines.append("    return _check")
    lines.append("")
    
    lines.append("# Routes")
    for endpoint in api.endpoints:
        method = endpoint.method.lower()
        req_model = f"{endpoint.request_model}" if endpoint.request_model else "None"
        resp_model = f" -> {endpoint.response_model}" if endpoint.response_model else ""
        
        args = []
        if endpoint.request_model:
            args.append(f"payload: {endpoint.request_model}")
            
        deps = []
        if endpoint.required_permission:
            deps.append(f"Depends(check_permissions('{endpoint.required_permission}'))")
            
        if deps:
            if args:
                args.append(f"_: Any = {deps[0]}")
            else:
                args.append(f"_: Any = {deps[0]}")
                
        args_str = ", ".join(args)
        
        func_name = "".join(c if c.isalnum() else "_" for c in endpoint.name).lower()
        if not func_name[0].isalpha():
            func_name = f"route_{func_name}"
        
        lines.append(f"@app.{method}('{endpoint.path}')")
        lines.append(f"def {func_name}({args_str}){resp_model}:")
        lines.append(f"    pass")
        lines.append("")
        
    return "\n".join(lines)


def _generate_frontend_html(ui: UISchema) -> str:
    """Generate minimal HTML frontend structure."""
    lines: list[str] = [
        "<!DOCTYPE html>",
        "<html>",
        "<head><title>Generated App</title></head>",
        "<body>",
        "  <nav id='navigation'>"
    ]
    
    for nav in ui.navigation:
        lines.append(f"    <a href='{nav.route}'>{nav.label}</a>")
        
    lines.append("  </nav>")
    lines.append("  <main id='content'>")
    
    for page in ui.pages:
        lines.append(f"    <div class='page' data-route='{page.route}' id='{page.name}'>")
        lines.append(f"      <h1>{page.name}</h1>")
        
        for form_id in page.form_ids:
            for form in ui.forms:
                if form.id == form_id:
                    lines.append(f"      <form id='{form.id}' action='{form.submit_action}'>")
                    for field in form.fields:
                        lines.append(f"        <input name='{field}' placeholder='{field}' />")
                    lines.append("        <button type='submit'>Submit</button>")
                    lines.append("      </form>")
                    
        for comp_id in page.component_ids:
            for comp in ui.components:
                if comp.id == comp_id:
                    lines.append(f"      <div id='{comp.id}' class='component {comp.component_type}'>")
                    if comp.bound_entity:
                        lines.append(f"        <!-- Bound to {comp.bound_entity} fields: {', '.join(comp.bound_fields)} -->")
                    lines.append("      </div>")
                    
        lines.append("    </div>")
        
    lines.append("  </main>")
    lines.append("</body>")
    lines.append("</html>")
    
    return "\n".join(lines)


def _generate_auth_mapping(auth: AuthSchema) -> str:
    """Generate JSON mapping for auth roles and policies."""
    config = {
        "roles": [r.name for r in auth.roles],
        "policies": [
            {
                "role": policy.role,
                "page_routes": list(policy.page_routes),
                "permissions": list(policy.permissions),
            } for policy in auth.access_policies
        ]
    }
    return json.dumps(config, indent=2)


def _verify_python_syntax(filepath: Path) -> bool:
    try:
        source = filepath.read_text(encoding="utf-8")
        ast.parse(source)
        return True
    except SyntaxError:
        return False
    except FileNotFoundError:
        return False


def _verify_sqlite_schema(filepath: Path) -> bool:
    try:
        schema_sql = filepath.read_text(encoding="utf-8")
        conn = sqlite3.connect(":memory:")
        conn.executescript(schema_sql)
        conn.close()
        return True
    except sqlite3.Error:
        return False
    except FileNotFoundError:
        return False
