from __future__ import annotations

from pathlib import Path

from compiler.contracts import (
    AppSpec,
    ArchitectureManifest,
    AuthAccessPolicy,
    AuthFeatureGate,
    AuthPermissionSchema,
    AuthRoleSchema,
    AuthSchema,
    CompilerStage,
)
from compiler.logging import DEFAULT_LOG_DIR, stage_execution


def generate_auth_schema(
    architecture: ArchitectureManifest,
    app_spec: AppSpec,
    log_dir: Path = DEFAULT_LOG_DIR,
) -> AuthSchema:
    with stage_execution(CompilerStage.AUTH_SCHEMA_GENERATION, log_dir=log_dir) as validation_errors:
        try:
            schema = _generate_auth_schema(architecture, app_spec)
            AuthSchema.model_validate(schema.model_dump())
            return schema
        except Exception as exc:
            validation_errors.append(str(exc))
            raise


def _generate_auth_schema(architecture: ArchitectureManifest, app_spec: AppSpec) -> AuthSchema:
    roles = tuple(
        AuthRoleSchema(
            name=role.name,
            source_intent_fields=role.source_intent_fields,
            rationale=f"{role.name} is copied from ArchitectureManifest roles.",
        )
        for role in architecture.roles
    )
    permissions = tuple(
        AuthPermissionSchema(
            role=permission.role,
            action=permission.action,
            resource=permission.resource,
            source_intent_fields=permission.source_intent_fields,
            rationale=f"{permission.role} can {permission.action} {permission.resource} by architecture permission.",
        )
        for permission in architecture.permissions
    )
    access_policies = tuple(
        AuthAccessPolicy(
            role=role.name,
            page_routes=tuple(page.route for page in architecture.pages if role.name in page.allowed_roles),
            permissions=tuple(
                f"{permission.action}:{permission.resource}"
                for permission in architecture.permissions
                if permission.role == role.name
            ),
            source_intent_fields=role.source_intent_fields,
            rationale=f"{role.name} access policy combines page visibility and resource permissions.",
        )
        for role in architecture.roles
    )
    feature_gating = tuple(
        AuthFeatureGate(
            feature=rule.id,
            roles=rule.referenced_roles,
            required_integration=_integration_for_rule(rule.source_intent_fields, architecture),
            source_intent_fields=rule.source_intent_fields,
            rationale=f"{rule.id} becomes an auth feature gate because it references roles.",
        )
        for rule in architecture.business_rules
        if rule.referenced_roles
    )
    return AuthSchema(
        roles=roles,
        permissions=permissions,
        access_policies=access_policies,
        feature_gating=feature_gating,
        source_intent_fields=("roles", "permissions", "business_rules"),
        rationale="The auth schema is generated from roles, permissions, page access, business rules, and integrations.",
    )


def _integration_for_rule(source_intent_fields: tuple[str, ...], architecture: ArchitectureManifest) -> str | None:
    if "integrations" not in source_intent_fields or not architecture.integrations:
        return None
    return architecture.integrations[0].provider
