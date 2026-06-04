from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class RationaleContract(StrictContract):
    rationale: str = Field(min_length=1)
    source_intent_fields: tuple[str, ...] = Field(default_factory=tuple)


class ApplicationType(StrEnum):
    CRM = "CRM"
    PROJECT_MANAGEMENT = "project_management"
    MARKETPLACE = "marketplace"
    LMS = "learning_management"
    ANALYTICS = "analytics"
    INTERNAL_TOOL = "internal_tool"
    SAAS = "saas"
    CUSTOM = "custom"


class Feature(RationaleContract):
    name: str = Field(min_length=1)


class Role(RationaleContract):
    name: str = Field(min_length=1)


class Plan(RationaleContract):
    name: str = Field(min_length=1)


class IntentEntity(RationaleContract):
    name: str = Field(min_length=1)


class Integration(RationaleContract):
    name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    required: bool
    capabilities: tuple[str, ...] = Field(default_factory=tuple)
    api_base_path: str | None = Field(default=None, pattern=r"^/")


class Assumption(RationaleContract):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ClarificationQuestion(RationaleContract):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    blocking: bool


class IntentIR(RationaleContract):
    application_type: ApplicationType
    features: tuple[Feature, ...] = Field(default_factory=tuple)
    roles: tuple[Role, ...] = Field(default_factory=tuple)
    entities: tuple[IntentEntity, ...] = Field(default_factory=tuple)
    integrations: tuple[Integration, ...] = Field(default_factory=tuple)
    plans: tuple[Plan, ...] = Field(default_factory=tuple)
    assumptions: tuple[Assumption, ...] = Field(default_factory=tuple)
    clarification_questions: tuple[ClarificationQuestion, ...] = Field(default_factory=tuple)


class FieldType(StrEnum):
    STRING = "string"
    TEXT = "text"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    DATE = "date"
    UUID = "uuid"
    EMAIL = "email"


class EntityField(RationaleContract):
    name: str = Field(min_length=1)
    field_type: FieldType
    required: bool = True
    unique: bool = False


class Entity(RationaleContract):
    name: str = Field(min_length=1)
    fields: tuple[EntityField, ...] = Field(default_factory=tuple)

    @field_validator("fields")
    @classmethod
    def field_names_are_unique(cls, fields: tuple[EntityField, ...]) -> tuple[EntityField, ...]:
        names = [field.name for field in fields]
        if len(names) != len(set(names)):
            raise ValueError("entity field names must be unique")
        return fields


class Page(RationaleContract):
    name: str = Field(min_length=1)
    route: str = Field(pattern=r"^/")
    allowed_roles: tuple[str, ...] = Field(default_factory=tuple)
    flow_names: tuple[str, ...] = Field(default_factory=tuple)


class UserFlow(RationaleContract):
    name: str = Field(min_length=1)
    steps: tuple[str, ...] = Field(min_length=1)
    related_pages: tuple[str, ...] = Field(default_factory=tuple)


class Permission(RationaleContract):
    role: str = Field(min_length=1)
    action: str = Field(min_length=1)
    resource: str = Field(min_length=1)


class BusinessRule(RationaleContract):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    applies_to: tuple[str, ...] = Field(default_factory=tuple)
    referenced_entities: tuple[str, ...] = Field(default_factory=tuple)
    referenced_roles: tuple[str, ...] = Field(default_factory=tuple)


class ArchitectureManifest(RationaleContract):
    entities: tuple[Entity, ...] = Field(default_factory=tuple)
    user_flows: tuple[UserFlow, ...] = Field(default_factory=tuple)
    pages: tuple[Page, ...] = Field(default_factory=tuple)
    roles: tuple[Role, ...] = Field(default_factory=tuple)
    permissions: tuple[Permission, ...] = Field(default_factory=tuple)
    business_rules: tuple[BusinessRule, ...] = Field(default_factory=tuple)
    integrations: tuple[Integration, ...] = Field(default_factory=tuple)
    assumptions: tuple[Assumption, ...] = Field(default_factory=tuple)
    clarification_questions: tuple[ClarificationQuestion, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def references_are_consistent(self) -> ArchitectureManifest:
        role_names = {role.name for role in self.roles}
        entity_names = {entity.name for entity in self.entities}
        flow_names = {flow.name for flow in self.user_flows}
        unknown_permission_roles = [permission.role for permission in self.permissions if permission.role not in role_names]
        unknown_page_roles = [role for page in self.pages for role in page.allowed_roles if role not in role_names]
        if unknown_permission_roles or unknown_page_roles:
            raise ValueError("permissions and page access rules must reference existing roles")
        roles_without_permissions = [role.name for role in self.roles if not any(permission.role == role.name for permission in self.permissions)]
        if roles_without_permissions:
            raise ValueError("every role must have at least one permission")
        pages_without_flows = [page.name for page in self.pages if not page.flow_names]
        unknown_page_flows = [flow for page in self.pages for flow in page.flow_names if flow not in flow_names]
        if pages_without_flows or unknown_page_flows:
            raise ValueError("every page must reference at least one existing user flow")
        rules_without_references = [rule.id for rule in self.business_rules if not rule.referenced_entities and not rule.referenced_roles]
        unknown_rule_entities = [entity for rule in self.business_rules for entity in rule.referenced_entities if entity not in entity_names]
        unknown_rule_roles = [role for rule in self.business_rules for role in rule.referenced_roles if role not in role_names]
        if rules_without_references or unknown_rule_entities or unknown_rule_roles:
            raise ValueError("business rules must reference existing entities or roles")
        architecture_elements = (
            [*self.entities, *self.user_flows, *self.pages, *self.roles, *self.permissions, *self.business_rules, *self.integrations]
        )
        missing_traceability = [element.rationale for element in architecture_elements if not element.source_intent_fields]
        if missing_traceability:
            raise ValueError("every architecture element must include source_intent_fields")
        return self


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class ApiEndpoint(RationaleContract):
    name: str = Field(min_length=1)
    method: HttpMethod
    path: str = Field(pattern=r"^/")
    request_entity: str | None = None
    response_entity: str | None = None
    required_permission: str | None = None


class UiComponent(RationaleContract):
    id: str = Field(min_length=1)
    component_type: str = Field(min_length=1)
    bound_entity: str | None = None
    bound_fields: tuple[str, ...] = Field(default_factory=tuple)


class DatabaseTable(RationaleContract):
    name: str = Field(min_length=1)
    entity: str = Field(min_length=1)
    fields: tuple[EntityField, ...] = Field(default_factory=tuple)


class AuthPolicy(RationaleContract):
    role: str = Field(min_length=1)
    permissions: tuple[str, ...] = Field(default_factory=tuple)


class UILayout(RationaleContract):
    name: str = Field(min_length=1)
    regions: tuple[str, ...] = Field(min_length=1)


class UIComponentSchema(RationaleContract):
    id: str = Field(min_length=1)
    component_type: str = Field(min_length=1)
    page_route: str = Field(pattern=r"^/")
    bound_entity: str | None = None
    bound_fields: tuple[str, ...] = Field(default_factory=tuple)


class UIFormSchema(RationaleContract):
    id: str = Field(min_length=1)
    page_route: str = Field(pattern=r"^/")
    entity: str = Field(min_length=1)
    fields: tuple[str, ...] = Field(default_factory=tuple)
    submit_action: str = Field(min_length=1)


class UINavigationItem(RationaleContract):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    route: str = Field(pattern=r"^/")
    allowed_roles: tuple[str, ...] = Field(min_length=1)


class UIRoleVisibility(RationaleContract):
    role: str = Field(min_length=1)
    page_routes: tuple[str, ...] = Field(default_factory=tuple)


class UIPageSchema(RationaleContract):
    name: str = Field(min_length=1)
    route: str = Field(pattern=r"^/")
    layout: str = Field(min_length=1)
    component_ids: tuple[str, ...] = Field(default_factory=tuple)
    form_ids: tuple[str, ...] = Field(default_factory=tuple)
    navigation_item_ids: tuple[str, ...] = Field(default_factory=tuple)
    role_visibility: tuple[str, ...] = Field(min_length=1)


class UISchema(RationaleContract):
    pages: tuple[UIPageSchema, ...] = Field(default_factory=tuple)
    layouts: tuple[UILayout, ...] = Field(default_factory=tuple)
    components: tuple[UIComponentSchema, ...] = Field(default_factory=tuple)
    forms: tuple[UIFormSchema, ...] = Field(default_factory=tuple)
    navigation: tuple[UINavigationItem, ...] = Field(default_factory=tuple)
    role_visibility: tuple[UIRoleVisibility, ...] = Field(default_factory=tuple)


class APIFieldSchema(RationaleContract):
    name: str = Field(min_length=1)
    field_type: FieldType
    required: bool


class APIModelSchema(RationaleContract):
    name: str = Field(min_length=1)
    fields: tuple[APIFieldSchema, ...] = Field(default_factory=tuple)


class APIValidationRule(RationaleContract):
    model: str = Field(min_length=1)
    field: str = Field(min_length=1)
    rule: str = Field(min_length=1)


class APIEndpointSchema(RationaleContract):
    name: str = Field(min_length=1)
    method: HttpMethod
    path: str = Field(pattern=r"^/")
    request_model: str | None = None
    response_model: str = Field(min_length=1)
    required_permission: str = Field(min_length=1)


class APISchema(RationaleContract):
    endpoints: tuple[APIEndpointSchema, ...] = Field(default_factory=tuple)
    methods: tuple[HttpMethod, ...] = Field(default_factory=tuple)
    request_models: tuple[APIModelSchema, ...] = Field(default_factory=tuple)
    response_models: tuple[APIModelSchema, ...] = Field(default_factory=tuple)
    validation_rules: tuple[APIValidationRule, ...] = Field(default_factory=tuple)


class DatabaseFieldSchema(RationaleContract):
    name: str = Field(min_length=1)
    field_type: FieldType
    nullable: bool
    unique: bool


class DatabaseRelationship(RationaleContract):
    from_table: str = Field(min_length=1)
    to_table: str = Field(min_length=1)
    relationship_type: str = Field(min_length=1)


class DatabaseConstraint(RationaleContract):
    table: str = Field(min_length=1)
    constraint_type: str = Field(min_length=1)
    fields: tuple[str, ...] = Field(min_length=1)


class DatabaseIndex(RationaleContract):
    table: str = Field(min_length=1)
    fields: tuple[str, ...] = Field(min_length=1)
    unique: bool


class DatabaseTableSchema(RationaleContract):
    name: str = Field(min_length=1)
    entity: str = Field(min_length=1)
    fields: tuple[DatabaseFieldSchema, ...] = Field(default_factory=tuple)


class DatabaseSchema(RationaleContract):
    tables: tuple[DatabaseTableSchema, ...] = Field(default_factory=tuple)
    fields: tuple[DatabaseFieldSchema, ...] = Field(default_factory=tuple)
    relationships: tuple[DatabaseRelationship, ...] = Field(default_factory=tuple)
    constraints: tuple[DatabaseConstraint, ...] = Field(default_factory=tuple)
    indexes: tuple[DatabaseIndex, ...] = Field(default_factory=tuple)


class AuthRoleSchema(RationaleContract):
    name: str = Field(min_length=1)


class AuthPermissionSchema(RationaleContract):
    role: str = Field(min_length=1)
    action: str = Field(min_length=1)
    resource: str = Field(min_length=1)


class AuthAccessPolicy(RationaleContract):
    role: str = Field(min_length=1)
    page_routes: tuple[str, ...] = Field(default_factory=tuple)
    permissions: tuple[str, ...] = Field(default_factory=tuple)


class AuthFeatureGate(RationaleContract):
    feature: str = Field(min_length=1)
    roles: tuple[str, ...] = Field(min_length=1)
    required_integration: str | None = None


class AuthSchema(RationaleContract):
    roles: tuple[AuthRoleSchema, ...] = Field(default_factory=tuple)
    permissions: tuple[AuthPermissionSchema, ...] = Field(default_factory=tuple)
    access_policies: tuple[AuthAccessPolicy, ...] = Field(default_factory=tuple)
    feature_gating: tuple[AuthFeatureGate, ...] = Field(default_factory=tuple)


class AppSpec(RationaleContract):
    application_type: ApplicationType
    entities: tuple[Entity, ...] = Field(default_factory=tuple)
    pages: tuple[Page, ...] = Field(default_factory=tuple)
    api_endpoints: tuple[ApiEndpoint, ...] = Field(default_factory=tuple)
    database_tables: tuple[DatabaseTable, ...] = Field(default_factory=tuple)
    auth_policies: tuple[AuthPolicy, ...] = Field(default_factory=tuple)
    ui_components: tuple[UiComponent, ...] = Field(default_factory=tuple)
    business_rules: tuple[BusinessRule, ...] = Field(default_factory=tuple)
    integrations: tuple[Integration, ...] = Field(default_factory=tuple)
    assumptions: tuple[Assumption, ...] = Field(default_factory=tuple)
    clarification_questions: tuple[ClarificationQuestion, ...] = Field(default_factory=tuple)


class CompilerStage(StrEnum):
    INTENT_EXTRACTION = "intent_extraction"
    ARCHITECTURE_PLANNING = "architecture_planning"
    NORMALIZATION = "normalization"
    UI_SCHEMA_GENERATION = "ui_schema_generation"
    API_SCHEMA_GENERATION = "api_schema_generation"
    DB_SCHEMA_GENERATION = "db_schema_generation"
    AUTH_SCHEMA_GENERATION = "auth_schema_generation"
    REFINEMENT = "refinement"
    VALIDATION = "validation"
    REPAIR = "repair"
    RUNTIME_GENERATION = "runtime_generation"


class StageExecutionLog(StrictContract):
    stage: CompilerStage
    start_time: datetime
    end_time: datetime
    latency_ms: float = Field(ge=0)
    validation_errors: tuple[str, ...] = Field(default_factory=tuple)
    repair_attempts: int = Field(ge=0, default=0)
    success_status: bool

    @model_validator(mode="after")
    def end_time_not_before_start_time(self) -> StageExecutionLog:
        if self.end_time < self.start_time:
            raise ValueError("end_time must be greater than or equal to start_time")
        return self


class ArchitectureDecision(RationaleContract):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    consequences: tuple[str, ...] = Field(default_factory=tuple)


class ArchitectureDecisionLog(StrictContract):
    decisions: tuple[ArchitectureDecision, ...]


def json_schema_for(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema()
