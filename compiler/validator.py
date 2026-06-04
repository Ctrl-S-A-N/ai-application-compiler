"""Phase 4 – Deterministic validation engine.

Pure rule-based validation of Phase 3 schema outputs.
No LLM calls.  Strict Pydantic outputs.  Execution logging.
"""

from __future__ import annotations

from pathlib import Path

from compiler.contracts import (
    APISchema,
    ArchitectureManifest,
    AuthSchema,
    CompilerStage,
    DatabaseSchema,
    HttpMethod,
    UISchema,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from compiler.logging import DEFAULT_LOG_DIR, stage_execution


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_schemas(
    ui_schema: UISchema,
    api_schema: APISchema,
    db_schema: DatabaseSchema,
    auth_schema: AuthSchema,
    architecture: ArchitectureManifest,
    log_dir: Path = DEFAULT_LOG_DIR,
) -> ValidationReport:
    """Run every validation rule and return a strict :class:`ValidationReport`.

    The validator itself never raises for schema defects – instead it
    accumulates issues.  Only unexpected internal errors propagate.
    """
    with stage_execution(CompilerStage.VALIDATION, log_dir=log_dir) as validation_errors:
        try:
            issues: list[ValidationIssue] = []

            # 1. Contract / JSON validity (round-trip)
            issues.extend(_check_contract_validity(ui_schema, "ui"))
            issues.extend(_check_contract_validity(api_schema, "api"))
            issues.extend(_check_contract_validity(db_schema, "db"))
            issues.extend(_check_contract_validity(auth_schema, "auth"))

            # 2. Required fields
            issues.extend(_check_required_fields(ui_schema, api_schema, db_schema, auth_schema))

            # 3. Type safety across layers
            issues.extend(_check_type_safety(api_schema, db_schema))

            # 4. Cross-layer consistency
            issues.extend(_check_ui_api_consistency(ui_schema, api_schema))
            issues.extend(_check_api_db_consistency(api_schema, db_schema))
            issues.extend(_check_auth_ui_consistency(auth_schema, ui_schema))
            issues.extend(_check_business_rules_consistency(architecture, db_schema, auth_schema))

            report = ValidationReport(
                issues=tuple(issues),
                valid=not any(issue.severity == ValidationSeverity.ERROR for issue in issues),
                layers_validated=("ui", "api", "db", "auth"),
                cross_layer_checks=("ui_api", "api_db", "auth_ui", "business_rules"),
            )

            # Propagate error-level issues into the execution log.
            for issue in issues:
                if issue.severity == ValidationSeverity.ERROR:
                    validation_errors.append(issue.message)

            return report
        except Exception as exc:
            validation_errors.append(str(exc))
            raise


# ---------------------------------------------------------------------------
# 1. Contract validity
# ---------------------------------------------------------------------------


def _check_contract_validity(schema, layer: str) -> list[ValidationIssue]:
    """Verify the schema round-trips through JSON without data loss."""
    issues: list[ValidationIssue] = []
    try:
        json_data = schema.model_dump(mode="json")
        type(schema).model_validate(json_data)
    except Exception as exc:
        issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                layer=layer,
                code="CONTRACT_INVALID",
                message=f"{layer} schema fails contract round-trip: {exc}",
            )
        )
    return issues


# ---------------------------------------------------------------------------
# 2. Required fields
# ---------------------------------------------------------------------------


_REQUIRED_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("ui", "pages", "UI schema must contain at least one page"),
    ("ui", "layouts", "UI schema must contain at least one layout"),
    ("ui", "components", "UI schema must contain at least one component"),
    ("api", "endpoints", "API schema must contain at least one endpoint"),
    ("api", "request_models", "API schema must contain at least one request model"),
    ("api", "response_models", "API schema must contain at least one response model"),
    ("db", "tables", "Database schema must contain at least one table"),
    ("auth", "roles", "Auth schema must contain at least one role"),
    ("auth", "permissions", "Auth schema must contain at least one permission"),
)


def _check_required_fields(
    ui_schema: UISchema,
    api_schema: APISchema,
    db_schema: DatabaseSchema,
    auth_schema: AuthSchema,
) -> list[ValidationIssue]:
    schemas = {"ui": ui_schema, "api": api_schema, "db": db_schema, "auth": auth_schema}
    issues: list[ValidationIssue] = []
    for layer, field_name, message in _REQUIRED_SECTIONS:
        value = getattr(schemas[layer], field_name, ())
        if not value:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    layer=layer,
                    code="REQUIRED_FIELD_EMPTY",
                    message=message,
                    source_ref=f"{layer}.{field_name}",
                )
            )
    return issues


# ---------------------------------------------------------------------------
# 3. Type safety
# ---------------------------------------------------------------------------


def _check_type_safety(api_schema: APISchema, db_schema: DatabaseSchema) -> list[ValidationIssue]:
    """API field types must match their corresponding DB field types."""
    issues: list[ValidationIssue] = []
    db_field_types: dict[str, dict[str, str]] = {}
    for table in db_schema.tables:
        db_field_types[table.entity] = {field.name: field.field_type for field in table.fields}

    for model in (*api_schema.request_models, *api_schema.response_models):
        entity_name = _extract_entity_name(model.name)
        if entity_name is None or entity_name not in db_field_types:
            continue
        db_fields = db_field_types[entity_name]
        for field in model.fields:
            if field.name in db_fields and field.field_type != db_fields[field.name]:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        layer="cross:api_db",
                        code="TYPE_MISMATCH",
                        message=(
                            f"Field '{field.name}' in {model.name} has type "
                            f"'{field.field_type}' but DB table for {entity_name} "
                            f"has type '{db_fields[field.name]}'"
                        ),
                        source_ref=f"{model.name}.{field.name}",
                    )
                )
    return issues


# ---------------------------------------------------------------------------
# 4a. UI ↔ API consistency
# ---------------------------------------------------------------------------


def _check_ui_api_consistency(ui_schema: UISchema, api_schema: APISchema) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    # Build lookup structures from API schema.
    endpoint_methods: dict[str, set[str]] = {}  # entity_name -> set of methods
    for endpoint in api_schema.endpoints:
        if endpoint.request_model:
            entity = _extract_entity_name(endpoint.request_model)
            if entity:
                endpoint_methods.setdefault(entity, set()).add(endpoint.method)
        if endpoint.response_model:
            entity = _extract_entity_name(endpoint.response_model)
            if entity:
                endpoint_methods.setdefault(entity, set()).add(endpoint.method)

    request_model_fields: dict[str, set[str]] = {
        model.name: {field.name for field in model.fields}
        for model in api_schema.request_models
    }
    response_model_fields: dict[str, set[str]] = {
        model.name: {field.name for field in model.fields}
        for model in api_schema.response_models
    }

    # Check 1: Forms map to endpoints.
    _ACTION_TO_METHOD = {"create": HttpMethod.POST, "update": HttpMethod.PATCH, "delete": HttpMethod.DELETE}
    for form in ui_schema.forms:
        parts = form.submit_action.split(":", maxsplit=1)
        if len(parts) == 2:
            action, entity = parts
            expected_method = _ACTION_TO_METHOD.get(action)
            if expected_method is not None:
                entity_methods = endpoint_methods.get(entity, set())
                if expected_method not in entity_methods:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            layer="cross:ui_api",
                            code="FORM_MISSING_ENDPOINT",
                            message=(
                                f"Form '{form.id}' has submit_action '{form.submit_action}' "
                                f"but no {expected_method} endpoint exists for entity '{entity}'"
                            ),
                            source_ref=form.id,
                        )
                    )

        # Check 2: Form fields exist in the request model.
        request_model_name = f"{form.entity}Request"
        if request_model_name in request_model_fields:
            model_fields = request_model_fields[request_model_name]
            for field_name in form.fields:
                if field_name not in model_fields:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            layer="cross:ui_api",
                            code="FORM_FIELD_NOT_IN_API",
                            message=(
                                f"Form '{form.id}' references field '{field_name}' "
                                f"not found in API model '{request_model_name}'"
                            ),
                            source_ref=f"{form.id}.{field_name}",
                        )
                    )

    # Check 3 & 4: Components map to response models and fields.
    for component in ui_schema.components:
        if component.bound_entity:
            response_model_name = f"{component.bound_entity}Response"
            entity_methods = endpoint_methods.get(component.bound_entity, set())
            if HttpMethod.GET not in entity_methods:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        layer="cross:ui_api",
                        code="COMPONENT_MISSING_ENDPOINT",
                        message=(
                            f"Component '{component.id}' is bound to entity "
                            f"'{component.bound_entity}' but no GET endpoint exists"
                        ),
                        source_ref=component.id,
                    )
                )
            if response_model_name in response_model_fields:
                model_fields = response_model_fields[response_model_name]
                for field_name in component.bound_fields:
                    if field_name not in model_fields:
                        issues.append(
                            ValidationIssue(
                                severity=ValidationSeverity.ERROR,
                                layer="cross:ui_api",
                                code="COMPONENT_FIELD_NOT_IN_API",
                                message=(
                                    f"Component '{component.id}' references field "
                                    f"'{field_name}' not in '{response_model_name}'"
                                ),
                                source_ref=f"{component.id}.{field_name}",
                            )
                        )

    return issues


# ---------------------------------------------------------------------------
# 4b. API ↔ DB consistency
# ---------------------------------------------------------------------------


def _check_api_db_consistency(api_schema: APISchema, db_schema: DatabaseSchema) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    db_entity_fields: dict[str, set[str]] = {
        table.entity: {field.name for field in table.fields}
        for table in db_schema.tables
    }

    for model in (*api_schema.request_models, *api_schema.response_models):
        entity_name = _extract_entity_name(model.name)
        if entity_name is None or entity_name not in db_entity_fields:
            continue  # Synthetic models (e.g. IntegrationStatusResponse) are not DB-backed.
        db_fields = db_entity_fields[entity_name]
        for field in model.fields:
            if field.name not in db_fields:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        layer="cross:api_db",
                        code="API_FIELD_NOT_IN_DB",
                        message=(
                            f"API model '{model.name}' has field '{field.name}' "
                            f"not found in DB table for entity '{entity_name}'"
                        ),
                        source_ref=f"{model.name}.{field.name}",
                    )
                )

    return issues


# ---------------------------------------------------------------------------
# 4c. Auth ↔ UI consistency
# ---------------------------------------------------------------------------


def _check_auth_ui_consistency(auth_schema: AuthSchema, ui_schema: UISchema) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    auth_role_names = {role.name for role in auth_schema.roles}
    ui_page_routes = {page.route for page in ui_schema.pages}

    # Check 1: Page role visibility references existing auth roles.
    for page in ui_schema.pages:
        for role in page.role_visibility:
            if role not in auth_role_names:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        layer="cross:auth_ui",
                        code="UI_ROLE_NOT_IN_AUTH",
                        message=(
                            f"Page '{page.name}' references role '{role}' "
                            f"not found in auth schema"
                        ),
                        source_ref=f"page:{page.route}",
                    )
                )

    # Check 2: Auth access policy routes reference existing UI pages.
    for policy in auth_schema.access_policies:
        for route in policy.page_routes:
            if route not in ui_page_routes:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        layer="cross:auth_ui",
                        code="AUTH_ROUTE_NOT_IN_UI",
                        message=(
                            f"Auth access policy for role '{policy.role}' references "
                            f"route '{route}' not found in UI pages"
                        ),
                        source_ref=f"policy:{policy.role}",
                    )
                )

    return issues


# ---------------------------------------------------------------------------
# 4d. Business rules ↔ All layers
# ---------------------------------------------------------------------------


def _check_business_rules_consistency(
    architecture: ArchitectureManifest,
    db_schema: DatabaseSchema,
    auth_schema: AuthSchema,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    db_entity_names = {table.entity for table in db_schema.tables}
    auth_role_names = {role.name for role in auth_schema.roles}

    for rule in architecture.business_rules:
        for entity in rule.referenced_entities:
            if entity not in db_entity_names:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        layer="cross:business_rules",
                        code="RULE_ENTITY_NOT_IN_DB",
                        message=(
                            f"Business rule '{rule.id}' references entity '{entity}' "
                            f"not found in database schema"
                        ),
                        source_ref=f"rule:{rule.id}",
                    )
                )
        for role in rule.referenced_roles:
            if role not in auth_role_names:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        layer="cross:business_rules",
                        code="RULE_ROLE_NOT_IN_AUTH",
                        message=(
                            f"Business rule '{rule.id}' references role '{role}' "
                            f"not found in auth schema"
                        ),
                        source_ref=f"rule:{rule.id}",
                    )
                )

    return issues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_entity_name(model_name: str) -> str | None:
    """Strip ``Request`` or ``Response`` suffix to recover the entity name."""
    for suffix in ("Request", "Response"):
        if model_name.endswith(suffix):
            return model_name[: -len(suffix)]
    return None
