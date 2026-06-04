from __future__ import annotations

from pathlib import Path

from compiler.contracts import (
    ArchitectureManifest,
    Assumption,
    BusinessRule,
    CompilerStage,
    Entity,
    EntityField,
    FieldType,
    IntentIR,
    Page,
    Permission,
    Role,
    UserFlow,
)
from compiler.logging import DEFAULT_LOG_DIR, stage_execution


def plan_architecture(intent: IntentIR, log_dir: Path = DEFAULT_LOG_DIR) -> ArchitectureManifest:
    with stage_execution(CompilerStage.ARCHITECTURE_PLANNING, log_dir=log_dir) as validation_errors:
        try:
            manifest = _plan_architecture(intent)
            ArchitectureManifest.model_validate(manifest.model_dump())
            return manifest
        except Exception as exc:
            validation_errors.append(str(exc))
            raise


def _plan_architecture(intent: IntentIR) -> ArchitectureManifest:
    roles = tuple(_role_with_traceability(role) for role in intent.roles) or (
        Role(
            name="admin",
            source_intent_fields=("assumptions",),
            rationale="An admin role is required for privileged application management.",
        ),
        Role(
            name="user",
            source_intent_fields=("assumptions",),
            rationale="A user role is required for standard application access.",
        ),
    )
    role_names = tuple(role.name for role in roles)
    entities = tuple(_entity_from_intent_entity(entity.name) for entity in intent.entities)
    if not entities:
        entities = (
            Entity(
                name="Record",
                fields=_default_fields_for("Record"),
                source_intent_fields=("assumptions", "clarification_questions"),
                rationale="A generic record entity keeps the architecture valid when the prompt lacks data details.",
            ),
        )

    permissions = _build_permissions(entities, role_names)
    user_flows = _build_user_flows(entities, role_names)
    pages = _build_pages(entities, role_names, user_flows)
    business_rules = _build_business_rules(intent, entities)
    assumptions = list(intent.assumptions)
    if any(question.blocking for question in intent.clarification_questions):
        assumptions.append(
            Assumption(
                id="architecture_subject_to_clarification",
                description="Architecture is provisional because at least one blocking clarification is open.",
                rationale="The planner must remain executable while preserving critical ambiguity for the reviewer.",
            )
        )

    return ArchitectureManifest(
        entities=entities,
        user_flows=user_flows,
        pages=pages,
        roles=roles,
        permissions=permissions,
        business_rules=business_rules,
        integrations=tuple(_integration_with_traceability(integration) for integration in intent.integrations),
        assumptions=tuple(assumptions),
        clarification_questions=intent.clarification_questions,
        rationale="The architecture is generated deterministically from IntentIR roles, entities, features, integrations, and assumptions.",
    )


def _entity_from_intent_entity(name: str) -> Entity:
    return Entity(
        name=name,
        fields=_default_fields_for(name),
        source_intent_fields=("entities",),
        rationale=f"{name} is promoted from IntentIR into a normalized architecture entity.",
    )


def _default_fields_for(entity_name: str) -> tuple[EntityField, ...]:
    fields = [
        EntityField(name="id", field_type=FieldType.UUID, required=True, unique=True, source_intent_fields=("entities",), rationale=f"{entity_name} needs a stable identifier."),
        EntityField(name="name", field_type=FieldType.STRING, required=True, source_intent_fields=("entities",), rationale=f"{entity_name} needs a human-readable name."),
        EntityField(name="created_at", field_type=FieldType.DATETIME, required=True, source_intent_fields=("entities",), rationale=f"{entity_name} needs creation tracking."),
        EntityField(name="updated_at", field_type=FieldType.DATETIME, required=True, source_intent_fields=("entities",), rationale=f"{entity_name} needs update tracking."),
    ]
    lower_name = entity_name.lower()
    if lower_name in {"contact", "user", "customer", "lead"}:
        fields.insert(2, EntityField(name="email", field_type=FieldType.EMAIL, required=False, unique=False, source_intent_fields=("entities", "features"), rationale=f"{entity_name} commonly needs email contact data."))
    if lower_name in {"invoice", "order", "deal"}:
        fields.insert(2, EntityField(name="amount", field_type=FieldType.FLOAT, required=False, source_intent_fields=("entities", "features"), rationale=f"{entity_name} commonly tracks monetary value."))
    return tuple(fields)


def _build_pages(entities: tuple[Entity, ...], role_names: tuple[str, ...], user_flows: tuple[UserFlow, ...]) -> tuple[Page, ...]:
    flow_names = {flow.name for flow in user_flows}
    pages = [
        Page(
            name="Dashboard",
            route="/dashboard",
            allowed_roles=role_names,
            flow_names=("Sign in and open dashboard",),
            source_intent_fields=("roles", "features"),
            rationale="A dashboard gives authenticated roles a landing page for core workflows.",
        )
    ]
    for entity in entities:
        route = f"/{entity.name.lower()}s"
        pages.append(
            Page(
                name=f"{entity.name} List",
                route=route,
                allowed_roles=role_names,
                flow_names=(f"Manage {entity.name}",) if f"Manage {entity.name}" in flow_names else ("Sign in and open dashboard",),
                source_intent_fields=("entities", "roles"),
                rationale=f"{entity.name} records need a list and management surface.",
            )
        )
    return tuple(pages)


def _build_permissions(entities: tuple[Entity, ...], role_names: tuple[str, ...]) -> tuple[Permission, ...]:
    permissions: list[Permission] = []
    for role_name in role_names:
        actions = ("create", "read", "update", "delete") if role_name == "admin" else ("read", "create", "update")
        for entity in entities:
            for action in actions:
                permissions.append(
                    Permission(
                        role=role_name,
                        action=action,
                        resource=entity.name,
                        source_intent_fields=("roles", "entities"),
                        rationale=f"{role_name} receives {action} access for {entity.name} based on its role level.",
                    )
                )
    return tuple(permissions)


def _build_user_flows(entities: tuple[Entity, ...], role_names: tuple[str, ...]) -> tuple[UserFlow, ...]:
    flows = [
        UserFlow(
            name="Sign in and open dashboard",
            steps=("open_login", "submit_credentials", "view_dashboard"),
            related_pages=("Dashboard",),
            source_intent_fields=("roles", "features"),
            rationale="Role-aware applications need an entry flow before protected pages.",
        )
    ]
    primary_role = "admin" if "admin" in role_names else role_names[0]
    for entity in entities:
        flows.append(
            UserFlow(
                name=f"Manage {entity.name}",
                steps=(f"{primary_role}_opens_{entity.name.lower()}_list", f"{primary_role}_creates_{entity.name.lower()}", f"{primary_role}_reviews_{entity.name.lower()}"),
                related_pages=(f"{entity.name} List",),
                source_intent_fields=("entities", "roles"),
                rationale=f"{entity.name} needs an end-to-end management flow for architecture validation.",
            )
        )
    return tuple(flows)


def _build_business_rules(intent: IntentIR, entities: tuple[Entity, ...]) -> tuple[BusinessRule, ...]:
    entity_names = tuple(entity.name for entity in entities)
    role_names = tuple(role.name for role in intent.roles) or ("admin", "user")
    rules = [
        BusinessRule(
            id="role_permissions_required",
            description="Every protected page and mutating operation must be covered by a declared role permission.",
            applies_to=("auth", "ui", "api"),
            referenced_entities=entity_names,
            referenced_roles=role_names,
            source_intent_fields=("roles", "entities"),
            rationale="Role consistency is required before later schema generation and validation.",
        )
    ]
    if intent.plans:
        rules.append(
            BusinessRule(
                id="plan_access_enforced",
                description="Plan-specific features must be checked before users access gated workflows.",
                applies_to=("auth", "ui", "api"),
                referenced_entities=entity_names,
                referenced_roles=role_names,
                source_intent_fields=("plans", "roles"),
                rationale="Plans in IntentIR imply access constraints across product layers.",
            )
        )
    if intent.integrations:
        rules.append(
            BusinessRule(
                id="integration_failures_are_visible",
                description="Required integrations must expose user-visible failure states and retry-safe server behavior.",
                applies_to=("ui", "api"),
                referenced_entities=entity_names,
                referenced_roles=role_names,
                source_intent_fields=("integrations", "roles"),
                rationale="External dependencies can fail and must be represented in the architecture.",
            )
        )
    if not entities:
        rules.append(
            BusinessRule(
                id="entity_model_requires_clarification",
                description="The data model must be clarified before runtime generation.",
                applies_to=("db", "api", "ui"),
                referenced_roles=role_names,
                source_intent_fields=("clarification_questions",),
                rationale="Runtime generation cannot be reliable without stable entities.",
            )
        )
    return tuple(rules)


def _role_with_traceability(role: Role) -> Role:
    if role.source_intent_fields:
        return role
    return role.model_copy(update={"source_intent_fields": ("roles",)})


def _integration_with_traceability(integration):
    updates = {}
    if not integration.source_intent_fields:
        updates["source_intent_fields"] = ("integrations",)
    if not integration.capabilities:
        updates["capabilities"] = ("external_api",)
    if integration.api_base_path is None:
        updates["api_base_path"] = f"/integrations/{integration.provider}"
    if not updates:
        return integration
    return integration.model_copy(update=updates)
