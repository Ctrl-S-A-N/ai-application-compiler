"""Phase 5 – Targeted repair engine.

Deterministic, rule-based repairs for validation failures.
Each repair targets exactly one schema layer.  No full regeneration.
No LLM calls.  Strict Pydantic outputs.  Execution logging.
"""

from __future__ import annotations

from pathlib import Path

from compiler.contracts import (
    APIFieldSchema,
    APIModelSchema,
    APISchema,
    ArchitectureManifest,
    AuthAccessPolicy,
    AuthPermissionSchema,
    AuthRoleSchema,
    AuthSchema,
    CompilerStage,
    DatabaseConstraint,
    DatabaseFieldSchema,
    DatabaseIndex,
    DatabaseSchema,
    DatabaseTableSchema,
    FieldType,
    HttpMethod,
    RepairAction,
    RepairLog,
    RepairResult,
    RepairTask,
    UISchema,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from compiler.logging import DEFAULT_LOG_DIR, stage_execution
from compiler.validator import validate_schemas


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def plan_repairs(report: ValidationReport) -> RepairTask:
    """Analyze a :class:`ValidationReport` and produce a :class:`RepairTask`.

    Each error-level issue generates exactly one :class:`RepairAction`
    targeting the affected layer.  Warnings are skipped.
    """
    actions: list[RepairAction] = []
    for issue in report.issues:
        if issue.severity != ValidationSeverity.ERROR:
            continue
        action = _action_for_issue(issue)
        if action is not None:
            actions.append(action)
    return RepairTask(
        actions=tuple(actions),
        source_validation_issues=len([i for i in report.issues if i.severity == ValidationSeverity.ERROR]),
    )


def execute_repairs(
    repair_task: RepairTask,
    ui_schema: UISchema,
    api_schema: APISchema,
    db_schema: DatabaseSchema,
    auth_schema: AuthSchema,
    architecture: ArchitectureManifest,
    log_dir: Path = DEFAULT_LOG_DIR,
) -> tuple[UISchema, APISchema, DatabaseSchema, AuthSchema, RepairLog]:
    """Execute all planned repairs and revalidate.

    Returns the (possibly repaired) schemas and a :class:`RepairLog`
    that records every repair outcome.
    """
    with stage_execution(
        CompilerStage.REPAIR,
        log_dir=log_dir,
        repair_attempts=len(repair_task.actions),
    ) as validation_errors:
        try:
            results: list[RepairResult] = []
            repaired_ui = ui_schema
            repaired_api = api_schema
            repaired_db = db_schema
            repaired_auth = auth_schema

            for action in repair_task.actions:
                result: RepairResult
                repaired_ui, repaired_api, repaired_db, repaired_auth, result = _apply_repair(
                    action, repaired_ui, repaired_api, repaired_db, repaired_auth, architecture,
                )
                results.append(result)

            # Revalidate after all repairs.
            post_report = validate_schemas(
                repaired_ui, repaired_api, repaired_db, repaired_auth, architecture, log_dir=log_dir,
            )

            issues_repaired = sum(1 for r in results if r.success)
            issues_unrepaired = len(results) - issues_repaired

            repair_log = RepairLog(
                results=tuple(results),
                total_issues=repair_task.source_validation_issues,
                issues_repaired=issues_repaired,
                issues_unrepaired=issues_unrepaired,
                revalidation_passed=post_report.valid,
            )

            if not post_report.valid:
                for issue in post_report.issues:
                    if issue.severity == ValidationSeverity.ERROR:
                        validation_errors.append(f"Post-repair: {issue.message}")

            return repaired_ui, repaired_api, repaired_db, repaired_auth, repair_log
        except Exception as exc:
            validation_errors.append(str(exc))
            raise


# ---------------------------------------------------------------------------
# Action planning: map issue codes to repair actions
# ---------------------------------------------------------------------------

_CODE_TO_LAYER: dict[str, str] = {
    "FORM_MISSING_ENDPOINT": "ui",
    "FORM_FIELD_NOT_IN_API": "ui",
    "COMPONENT_MISSING_ENDPOINT": "ui",
    "COMPONENT_FIELD_NOT_IN_API": "ui",
    "API_FIELD_NOT_IN_DB": "db",
    "TYPE_MISMATCH": "api",
    "UI_ROLE_NOT_IN_AUTH": "auth",
    "AUTH_ROUTE_NOT_IN_UI": "auth",
    "RULE_ENTITY_NOT_IN_DB": "db",
    "RULE_ROLE_NOT_IN_AUTH": "auth",
    "REQUIRED_FIELD_EMPTY": "unknown",
    "CONTRACT_INVALID": "unknown",
}

_CODE_TO_REPAIR: dict[str, str] = {
    "FORM_MISSING_ENDPOINT": "remove_orphan_form",
    "FORM_FIELD_NOT_IN_API": "remove_orphan_form_field",
    "COMPONENT_MISSING_ENDPOINT": "remove_component_binding",
    "COMPONENT_FIELD_NOT_IN_API": "remove_component_field",
    "API_FIELD_NOT_IN_DB": "add_db_field",
    "TYPE_MISMATCH": "fix_api_field_type",
    "UI_ROLE_NOT_IN_AUTH": "add_auth_role",
    "AUTH_ROUTE_NOT_IN_UI": "remove_auth_route",
    "RULE_ENTITY_NOT_IN_DB": "add_db_table_stub",
    "RULE_ROLE_NOT_IN_AUTH": "add_auth_role",
}


def _action_for_issue(issue: ValidationIssue) -> RepairAction | None:
    layer = _CODE_TO_LAYER.get(issue.code)
    repair = _CODE_TO_REPAIR.get(issue.code)
    if layer is None or repair is None or layer == "unknown":
        return None
    return RepairAction(
        error_code=issue.code,
        affected_layer=layer,
        repair_action=repair,
        source_ref=issue.source_ref,
    )


# ---------------------------------------------------------------------------
# Repair execution: dispatch to per-layer handlers
# ---------------------------------------------------------------------------


def _apply_repair(
    action: RepairAction,
    ui: UISchema,
    api: APISchema,
    db: DatabaseSchema,
    auth: AuthSchema,
    architecture: ArchitectureManifest,
) -> tuple[UISchema, APISchema, DatabaseSchema, AuthSchema, RepairResult]:
    """Dispatch a single repair action to the correct layer handler."""
    handler = _REPAIR_HANDLERS.get(action.repair_action)
    if handler is None:
        result = RepairResult(
            error_code=action.error_code,
            affected_layer=action.affected_layer,
            repair_action=action.repair_action,
            repaired_artifact=action.affected_layer,
            success=False,
            detail=f"No handler for repair action '{action.repair_action}'",
        )
        return ui, api, db, auth, result
    return handler(action, ui, api, db, auth, architecture)


# ---------------------------------------------------------------------------
# UI-layer repairs
# ---------------------------------------------------------------------------


def _repair_remove_orphan_form(
    action: RepairAction, ui: UISchema, api: APISchema, db: DatabaseSchema, auth: AuthSchema,
    architecture: ArchitectureManifest,
) -> tuple[UISchema, APISchema, DatabaseSchema, AuthSchema, RepairResult]:
    """Remove a form whose submit_action has no matching API endpoint."""
    ref = action.source_ref or ""
    ui_dict = ui.model_dump()
    original_count = len(ui_dict["forms"])
    ui_dict["forms"] = [f for f in ui_dict["forms"] if f["id"] != ref]
    removed = original_count - len(ui_dict["forms"])
    # Also clean form_ids from pages.
    for page in ui_dict["pages"]:
        page["form_ids"] = tuple(fid for fid in page["form_ids"] if fid != ref)
    repaired_ui = UISchema.model_validate(ui_dict)
    return repaired_ui, api, db, auth, RepairResult(
        error_code=action.error_code,
        affected_layer="ui",
        repair_action=action.repair_action,
        repaired_artifact="UISchema",
        success=removed > 0,
        detail=f"Removed {removed} orphan form(s) with id '{ref}'" if removed else f"Form '{ref}' not found",
    )


def _repair_remove_orphan_form_field(
    action: RepairAction, ui: UISchema, api: APISchema, db: DatabaseSchema, auth: AuthSchema,
    architecture: ArchitectureManifest,
) -> tuple[UISchema, APISchema, DatabaseSchema, AuthSchema, RepairResult]:
    """Remove a form field that doesn't exist in the API request model."""
    ref = action.source_ref or ""
    parts = ref.rsplit(".", maxsplit=1)
    if len(parts) != 2:
        return ui, api, db, auth, RepairResult(
            error_code=action.error_code, affected_layer="ui",
            repair_action=action.repair_action, repaired_artifact="UISchema",
            success=False, detail=f"Cannot parse source_ref '{ref}'",
        )
    form_id, field_name = parts

    # Build set of valid fields for each entity from API request models.
    api_fields_by_entity: dict[str, set[str]] = {}
    for model in api.request_models:
        entity_name = _extract_entity_name(model.name)
        if entity_name:
            api_fields_by_entity[entity_name] = {f.name for f in model.fields}

    ui_dict = ui.model_dump()
    removed = False
    for form in ui_dict["forms"]:
        if form["id"] == form_id:
            valid_fields = api_fields_by_entity.get(form["entity"], set())
            form["fields"] = tuple(f for f in form["fields"] if f in valid_fields)
            removed = True
    repaired_ui = UISchema.model_validate(ui_dict)
    return repaired_ui, api, db, auth, RepairResult(
        error_code=action.error_code, affected_layer="ui",
        repair_action=action.repair_action, repaired_artifact="UISchema",
        success=removed, detail=f"Removed invalid field '{field_name}' from form '{form_id}'",
    )


def _repair_remove_component_binding(
    action: RepairAction, ui: UISchema, api: APISchema, db: DatabaseSchema, auth: AuthSchema,
    architecture: ArchitectureManifest,
) -> tuple[UISchema, APISchema, DatabaseSchema, AuthSchema, RepairResult]:
    """Clear bound_entity on a component whose entity has no GET endpoint."""
    ref = action.source_ref or ""
    ui_dict = ui.model_dump()
    repaired = False
    for component in ui_dict["components"]:
        if component["id"] == ref:
            component["bound_entity"] = None
            component["bound_fields"] = ()
            repaired = True
    repaired_ui = UISchema.model_validate(ui_dict)
    return repaired_ui, api, db, auth, RepairResult(
        error_code=action.error_code, affected_layer="ui",
        repair_action=action.repair_action, repaired_artifact="UISchema",
        success=repaired, detail=f"Cleared entity binding on component '{ref}'",
    )


def _repair_remove_component_field(
    action: RepairAction, ui: UISchema, api: APISchema, db: DatabaseSchema, auth: AuthSchema,
    architecture: ArchitectureManifest,
) -> tuple[UISchema, APISchema, DatabaseSchema, AuthSchema, RepairResult]:
    """Remove a component bound_field that is not in the API response model."""
    ref = action.source_ref or ""
    parts = ref.rsplit(".", maxsplit=1)
    if len(parts) != 2:
        return ui, api, db, auth, RepairResult(
            error_code=action.error_code, affected_layer="ui",
            repair_action=action.repair_action, repaired_artifact="UISchema",
            success=False, detail=f"Cannot parse source_ref '{ref}'",
        )
    component_id, field_name = parts

    # Build valid response fields lookup.
    api_response_fields: dict[str, set[str]] = {}
    for model in api.response_models:
        entity_name = _extract_entity_name(model.name)
        if entity_name:
            api_response_fields[entity_name] = {f.name for f in model.fields}

    ui_dict = ui.model_dump()
    repaired = False
    for component in ui_dict["components"]:
        if component["id"] == component_id and component.get("bound_entity"):
            valid = api_response_fields.get(component["bound_entity"], set())
            component["bound_fields"] = tuple(f for f in component["bound_fields"] if f in valid)
            repaired = True
    repaired_ui = UISchema.model_validate(ui_dict)
    return repaired_ui, api, db, auth, RepairResult(
        error_code=action.error_code, affected_layer="ui",
        repair_action=action.repair_action, repaired_artifact="UISchema",
        success=repaired, detail=f"Removed field '{field_name}' from component '{component_id}'",
    )


# ---------------------------------------------------------------------------
# DB-layer repairs
# ---------------------------------------------------------------------------


def _repair_add_db_field(
    action: RepairAction, ui: UISchema, api: APISchema, db: DatabaseSchema, auth: AuthSchema,
    architecture: ArchitectureManifest,
) -> tuple[UISchema, APISchema, DatabaseSchema, AuthSchema, RepairResult]:
    """Add a missing field to the DB table to match the API model."""
    ref = action.source_ref or ""
    parts = ref.rsplit(".", maxsplit=1)
    if len(parts) != 2:
        return ui, api, db, auth, RepairResult(
            error_code=action.error_code, affected_layer="db",
            repair_action=action.repair_action, repaired_artifact="DatabaseSchema",
            success=False, detail=f"Cannot parse source_ref '{ref}'",
        )
    model_name, field_name = parts
    entity_name = _extract_entity_name(model_name)
    if entity_name is None:
        return ui, api, db, auth, RepairResult(
            error_code=action.error_code, affected_layer="db",
            repair_action=action.repair_action, repaired_artifact="DatabaseSchema",
            success=False, detail=f"Cannot extract entity from model '{model_name}'",
        )

    # Find the field type from the API model.
    api_field_type = _find_api_field_type(api, model_name, field_name)

    db_dict = db.model_dump()
    repaired = False
    new_field = {
        "name": field_name,
        "field_type": api_field_type,
        "nullable": True,
        "unique": False,
        "source_intent_fields": ("repair",),
        "rationale": f"Added by repair engine to match API model '{model_name}'.",
    }
    for table in db_dict["tables"]:
        if table["entity"] == entity_name:
            existing_names = {f["name"] for f in table["fields"]}
            if field_name not in existing_names:
                table["fields"] = list(table["fields"]) + [new_field]
                repaired = True
    # Also add to top-level fields.
    if repaired:
        db_dict["fields"] = list(db_dict["fields"]) + [new_field]
    repaired_db = DatabaseSchema.model_validate(db_dict)
    return ui, api, repaired_db, auth, RepairResult(
        error_code=action.error_code, affected_layer="db",
        repair_action=action.repair_action, repaired_artifact="DatabaseSchema",
        success=repaired,
        detail=f"Added field '{field_name}' to DB table for entity '{entity_name}'" if repaired else f"Table for '{entity_name}' not found",
    )


def _repair_add_db_table_stub(
    action: RepairAction, ui: UISchema, api: APISchema, db: DatabaseSchema, auth: AuthSchema,
    architecture: ArchitectureManifest,
) -> tuple[UISchema, APISchema, DatabaseSchema, AuthSchema, RepairResult]:
    """Add a stub DB table for a business-rule-referenced entity that is missing."""
    ref = action.source_ref or ""
    # source_ref format: "rule:{rule_id}"
    rule_id = ref.removeprefix("rule:") if ref.startswith("rule:") else ref

    # Find the entity name from the business rule.
    missing_entities: list[str] = []
    db_entity_names = {table.entity for table in db.tables}
    for rule in architecture.business_rules:
        if rule.id == rule_id:
            missing_entities = [e for e in rule.referenced_entities if e not in db_entity_names]
            break

    if not missing_entities:
        return ui, api, db, auth, RepairResult(
            error_code=action.error_code, affected_layer="db",
            repair_action=action.repair_action, repaired_artifact="DatabaseSchema",
            success=False, detail=f"No missing entities found for rule '{rule_id}'",
        )

    db_dict = db.model_dump()
    for entity_name in missing_entities:
        table_name = f"{_slug(entity_name)}s"
        id_field = {
            "name": "id", "field_type": "uuid", "nullable": False, "unique": True,
            "source_intent_fields": ("repair",),
            "rationale": f"Stub primary key added by repair engine for entity '{entity_name}'.",
        }
        name_field = {
            "name": "name", "field_type": "string", "nullable": False, "unique": False,
            "source_intent_fields": ("repair",),
            "rationale": f"Stub name field added by repair engine for entity '{entity_name}'.",
        }
        created_at_field = {
            "name": "created_at", "field_type": "datetime", "nullable": False, "unique": False,
            "source_intent_fields": ("repair",),
            "rationale": f"Stub timestamp added by repair engine for entity '{entity_name}'.",
        }
        updated_at_field = {
            "name": "updated_at", "field_type": "datetime", "nullable": False, "unique": False,
            "source_intent_fields": ("repair",),
            "rationale": f"Stub timestamp added by repair engine for entity '{entity_name}'.",
        }
        stub_table = {
            "name": table_name,
            "entity": entity_name,
            "fields": [id_field, name_field, created_at_field, updated_at_field],
            "source_intent_fields": ("repair",),
            "rationale": f"Stub table created by repair engine for business rule '{rule_id}'.",
        }
        db_dict["tables"] = list(db_dict["tables"]) + [stub_table]
        db_dict["fields"] = list(db_dict["fields"]) + [id_field, name_field, created_at_field, updated_at_field]
        db_dict["constraints"] = list(db_dict["constraints"]) + [{
            "table": table_name, "constraint_type": "primary_key", "fields": ("id",),
            "source_intent_fields": ("repair",),
            "rationale": f"Primary key constraint for stub table '{table_name}'.",
        }]

    repaired_db = DatabaseSchema.model_validate(db_dict)
    return ui, api, repaired_db, auth, RepairResult(
        error_code=action.error_code, affected_layer="db",
        repair_action=action.repair_action, repaired_artifact="DatabaseSchema",
        success=True,
        detail=f"Added stub DB table(s) for entities: {', '.join(missing_entities)}",
    )


# ---------------------------------------------------------------------------
# API-layer repairs
# ---------------------------------------------------------------------------


def _repair_fix_api_field_type(
    action: RepairAction, ui: UISchema, api: APISchema, db: DatabaseSchema, auth: AuthSchema,
    architecture: ArchitectureManifest,
) -> tuple[UISchema, APISchema, DatabaseSchema, AuthSchema, RepairResult]:
    """Correct an API field type to match the DB field type."""
    ref = action.source_ref or ""
    parts = ref.rsplit(".", maxsplit=1)
    if len(parts) != 2:
        return ui, api, db, auth, RepairResult(
            error_code=action.error_code, affected_layer="api",
            repair_action=action.repair_action, repaired_artifact="APISchema",
            success=False, detail=f"Cannot parse source_ref '{ref}'",
        )
    model_name, field_name = parts
    entity_name = _extract_entity_name(model_name)

    # Look up the correct type from the DB.
    db_type: str | None = None
    if entity_name:
        for table in db.tables:
            if table.entity == entity_name:
                for field in table.fields:
                    if field.name == field_name:
                        db_type = field.field_type
                        break

    if db_type is None:
        return ui, api, db, auth, RepairResult(
            error_code=action.error_code, affected_layer="api",
            repair_action=action.repair_action, repaired_artifact="APISchema",
            success=False, detail=f"DB type for '{field_name}' in entity '{entity_name}' not found",
        )

    api_dict = api.model_dump()
    repaired = False
    for collection in ("request_models", "response_models"):
        for model in api_dict[collection]:
            if model["name"] == model_name or (entity_name and _extract_entity_name(model["name"]) == entity_name):
                for field in model["fields"]:
                    if field["name"] == field_name and field["field_type"] != db_type:
                        field["field_type"] = db_type
                        repaired = True

    repaired_api = APISchema.model_validate(api_dict)
    return ui, repaired_api, db, auth, RepairResult(
        error_code=action.error_code, affected_layer="api",
        repair_action=action.repair_action, repaired_artifact="APISchema",
        success=repaired,
        detail=f"Fixed type of '{field_name}' in '{model_name}' to '{db_type}'" if repaired else f"Field '{field_name}' not found in API models",
    )


# ---------------------------------------------------------------------------
# Auth-layer repairs
# ---------------------------------------------------------------------------


def _repair_add_auth_role(
    action: RepairAction, ui: UISchema, api: APISchema, db: DatabaseSchema, auth: AuthSchema,
    architecture: ArchitectureManifest,
) -> tuple[UISchema, APISchema, DatabaseSchema, AuthSchema, RepairResult]:
    """Add a missing role to the auth schema."""
    # Determine which roles are missing.
    auth_role_names = {role.name for role in auth.roles}

    missing_roles: set[str] = set()
    if action.error_code == "UI_ROLE_NOT_IN_AUTH":
        # Collect roles from UI pages.
        for page in ui.pages:
            for role in page.role_visibility:
                if role not in auth_role_names:
                    missing_roles.add(role)
    elif action.error_code == "RULE_ROLE_NOT_IN_AUTH":
        # Collect roles from business rules.
        for rule in architecture.business_rules:
            for role in rule.referenced_roles:
                if role not in auth_role_names:
                    missing_roles.add(role)

    if not missing_roles:
        return ui, api, db, auth, RepairResult(
            error_code=action.error_code, affected_layer="auth",
            repair_action=action.repair_action, repaired_artifact="AuthSchema",
            success=False, detail="No missing roles identified",
        )

    auth_dict = auth.model_dump()

    # Collect all entity names for permission generation.
    entity_names = [e.name for e in architecture.entities]

    for role_name in sorted(missing_roles):
        auth_dict["roles"] = list(auth_dict["roles"]) + [{
            "name": role_name,
            "source_intent_fields": ("repair",),
            "rationale": f"Role '{role_name}' added by repair engine to satisfy cross-layer references.",
        }]
        # Grant default permissions.
        for entity_name in entity_names:
            for perm_action in ("read", "create", "update"):
                auth_dict["permissions"] = list(auth_dict["permissions"]) + [{
                    "role": role_name, "action": perm_action, "resource": entity_name,
                    "source_intent_fields": ("repair",),
                    "rationale": f"Default {perm_action} permission for repaired role '{role_name}'.",
                }]
        # Create access policy with all UI page routes this role can see.
        page_routes = tuple(
            page.route for page in ui.pages
            if role_name in page.role_visibility
        )
        if page_routes:
            auth_dict["access_policies"] = list(auth_dict["access_policies"]) + [{
                "role": role_name,
                "page_routes": page_routes,
                "permissions": tuple(f"{a}:{e}" for e in entity_names for a in ("read", "create", "update")),
                "source_intent_fields": ("repair",),
                "rationale": f"Access policy for repaired role '{role_name}'.",
            }]

    repaired_auth = AuthSchema.model_validate(auth_dict)
    return ui, api, db, repaired_auth, RepairResult(
        error_code=action.error_code, affected_layer="auth",
        repair_action=action.repair_action, repaired_artifact="AuthSchema",
        success=True,
        detail=f"Added auth role(s): {', '.join(sorted(missing_roles))}",
    )


def _repair_remove_auth_route(
    action: RepairAction, ui: UISchema, api: APISchema, db: DatabaseSchema, auth: AuthSchema,
    architecture: ArchitectureManifest,
) -> tuple[UISchema, APISchema, DatabaseSchema, AuthSchema, RepairResult]:
    """Remove access policy routes that don't exist in the UI."""
    ui_page_routes = {page.route for page in ui.pages}
    auth_dict = auth.model_dump()
    removed_count = 0
    for policy in auth_dict["access_policies"]:
        original = list(policy["page_routes"])
        policy["page_routes"] = tuple(r for r in original if r in ui_page_routes)
        removed_count += len(original) - len(policy["page_routes"])

    repaired_auth = AuthSchema.model_validate(auth_dict)
    return ui, api, db, repaired_auth, RepairResult(
        error_code=action.error_code, affected_layer="auth",
        repair_action=action.repair_action, repaired_artifact="AuthSchema",
        success=removed_count > 0,
        detail=f"Removed {removed_count} orphan route(s) from auth access policies",
    )


# ---------------------------------------------------------------------------
# Handler dispatch table
# ---------------------------------------------------------------------------

_REPAIR_HANDLERS = {
    "remove_orphan_form": _repair_remove_orphan_form,
    "remove_orphan_form_field": _repair_remove_orphan_form_field,
    "remove_component_binding": _repair_remove_component_binding,
    "remove_component_field": _repair_remove_component_field,
    "add_db_field": _repair_add_db_field,
    "add_db_table_stub": _repair_add_db_table_stub,
    "fix_api_field_type": _repair_fix_api_field_type,
    "add_auth_role": _repair_add_auth_role,
    "remove_auth_route": _repair_remove_auth_route,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_entity_name(model_name: str) -> str | None:
    """Strip ``Request`` or ``Response`` suffix to recover the entity name."""
    for suffix in ("Request", "Response"):
        if model_name.endswith(suffix):
            return model_name[: -len(suffix)]
    return None


def _find_api_field_type(api: APISchema, model_name: str, field_name: str) -> str:
    """Look up a field's type from the API model, defaulting to string."""
    for model in (*api.request_models, *api.response_models):
        if model.name == model_name:
            for field in model.fields:
                if field.name == field_name:
                    return field.field_type
    return FieldType.STRING


def _slug(value: str) -> str:
    normalized = "".join(c.lower() if c.isalnum() else "_" for c in value)
    return "_".join(part for part in normalized.split("_") if part)
