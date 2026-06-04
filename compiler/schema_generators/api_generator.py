from __future__ import annotations

from pathlib import Path

from compiler.contracts import (
    APIEndpointSchema,
    APIFieldSchema,
    APIModelSchema,
    APISchema,
    APIValidationRule,
    AppSpec,
    ArchitectureManifest,
    CompilerStage,
    Entity,
    FieldType,
    HttpMethod,
)
from compiler.logging import DEFAULT_LOG_DIR, stage_execution


def generate_api_schema(
    architecture: ArchitectureManifest,
    app_spec: AppSpec,
    log_dir: Path = DEFAULT_LOG_DIR,
) -> APISchema:
    with stage_execution(CompilerStage.API_SCHEMA_GENERATION, log_dir=log_dir) as validation_errors:
        try:
            schema = _generate_api_schema(architecture, app_spec)
            APISchema.model_validate(schema.model_dump())
            return schema
        except Exception as exc:
            validation_errors.append(str(exc))
            raise


def _generate_api_schema(architecture: ArchitectureManifest, app_spec: AppSpec) -> APISchema:
    request_models: list[APIModelSchema] = []
    response_models: list[APIModelSchema] = []
    validation_rules: list[APIValidationRule] = []
    endpoints: list[APIEndpointSchema] = []

    for entity in architecture.entities:
        request_models.append(_model_for_entity(entity, "Request", include_id=False))
        response_models.append(_model_for_entity(entity, "Response", include_id=True))
        validation_rules.extend(_validation_rules_for_entity(entity))
        endpoints.extend(_endpoints_for_entity(entity, architecture))

    for integration in architecture.integrations:
        endpoints.append(
            APIEndpointSchema(
                name=f"{integration.name} Status",
                method=HttpMethod.GET,
                path=f"{integration.api_base_path}/status",
                request_model=None,
                response_model="IntegrationStatusResponse",
                required_permission="admin:read:integration",
                source_intent_fields=integration.source_intent_fields,
                rationale=f"{integration.name} needs a status endpoint for execution-aware integration checks.",
            )
        )
    if architecture.integrations:
        response_models.append(
            APIModelSchema(
                name="IntegrationStatusResponse",
                fields=(
                    APIFieldSchema(name="provider", field_type=FieldType.STRING, required=True, source_intent_fields=("integrations",), rationale="Provider identifies the integration."),
                    APIFieldSchema(name="available", field_type=FieldType.BOOLEAN, required=True, source_intent_fields=("integrations",), rationale="Availability reports integration health."),
                ),
                source_intent_fields=("integrations",),
                rationale="Integration status responses are shared by generated integration endpoints.",
            )
        )

    return APISchema(
        endpoints=tuple(endpoints),
        methods=tuple(dict.fromkeys(endpoint.method for endpoint in endpoints)),
        request_models=tuple(request_models),
        response_models=tuple(response_models),
        validation_rules=tuple(validation_rules),
        source_intent_fields=("entities", "permissions", "integrations"),
        rationale="The API schema is generated from entities, permissions, and integration metadata without prompt parsing.",
    )


def _model_for_entity(entity: Entity, suffix: str, include_id: bool) -> APIModelSchema:
    return APIModelSchema(
        name=f"{entity.name}{suffix}",
        fields=tuple(
            APIFieldSchema(
                name=field.name,
                field_type=field.field_type,
                required=field.required,
                source_intent_fields=field.source_intent_fields,
                rationale=f"{field.name} is copied from the architecture entity field contract.",
            )
            for field in entity.fields
            if include_id or field.name != "id"
        ),
        source_intent_fields=entity.source_intent_fields,
        rationale=f"{entity.name}{suffix} is derived from the {entity.name} architecture entity.",
    )


def _validation_rules_for_entity(entity: Entity) -> list[APIValidationRule]:
    rules: list[APIValidationRule] = []
    for field in entity.fields:
        if field.required:
            rules.append(
                APIValidationRule(
                    model=f"{entity.name}Request",
                    field=field.name,
                    rule="required",
                    source_intent_fields=field.source_intent_fields,
                    rationale=f"{field.name} is required in the architecture field contract.",
                )
            )
        if field.unique:
            rules.append(
                APIValidationRule(
                    model=f"{entity.name}Request",
                    field=field.name,
                    rule="unique",
                    source_intent_fields=field.source_intent_fields,
                    rationale=f"{field.name} is unique in the architecture field contract.",
                )
            )
    return rules


def _endpoints_for_entity(entity: Entity, architecture: ArchitectureManifest) -> list[APIEndpointSchema]:
    base_path = f"/api/{_slug(entity.name)}s"
    return [
        APIEndpointSchema(
            name=f"List {entity.name}",
            method=HttpMethod.GET,
            path=base_path,
            response_model=f"{entity.name}Response",
            required_permission=_permission_for(architecture, "read", entity.name),
            source_intent_fields=("entities", "permissions"),
            rationale=f"{entity.name} read permissions map to a list endpoint.",
        ),
        APIEndpointSchema(
            name=f"Create {entity.name}",
            method=HttpMethod.POST,
            path=base_path,
            request_model=f"{entity.name}Request",
            response_model=f"{entity.name}Response",
            required_permission=_permission_for(architecture, "create", entity.name),
            source_intent_fields=("entities", "permissions"),
            rationale=f"{entity.name} create permissions map to a create endpoint.",
        ),
        APIEndpointSchema(
            name=f"Update {entity.name}",
            method=HttpMethod.PATCH,
            path=f"{base_path}/{{id}}",
            request_model=f"{entity.name}Request",
            response_model=f"{entity.name}Response",
            required_permission=_permission_for(architecture, "update", entity.name),
            source_intent_fields=("entities", "permissions"),
            rationale=f"{entity.name} update permissions map to an update endpoint.",
        ),
        APIEndpointSchema(
            name=f"Delete {entity.name}",
            method=HttpMethod.DELETE,
            path=f"{base_path}/{{id}}",
            response_model=f"{entity.name}Response",
            required_permission=_permission_for(architecture, "delete", entity.name),
            source_intent_fields=("entities", "permissions"),
            rationale=f"{entity.name} delete permissions map to a delete endpoint.",
        ),
    ]


def _permission_for(architecture: ArchitectureManifest, action: str, resource: str) -> str:
    for permission in architecture.permissions:
        if permission.action == action and permission.resource == resource:
            return f"{permission.role}:{permission.action}:{permission.resource}"
    return f"admin:{action}:{resource}"


def _slug(value: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else "_" for character in value)
    return "_".join(part for part in normalized.split("_") if part)
