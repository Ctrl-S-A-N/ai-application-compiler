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


class UserFlow(RationaleContract):
    name: str = Field(min_length=1)
    steps: tuple[str, ...] = Field(min_length=1)


class Permission(RationaleContract):
    role: str = Field(min_length=1)
    action: str = Field(min_length=1)
    resource: str = Field(min_length=1)


class BusinessRule(RationaleContract):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    applies_to: tuple[str, ...] = Field(default_factory=tuple)


class Integration(RationaleContract):
    name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    required: bool


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
    def references_existing_roles(self) -> ArchitectureManifest:
        role_names = {role.name for role in self.roles}
        unknown_permission_roles = [permission.role for permission in self.permissions if permission.role not in role_names]
        unknown_page_roles = [role for page in self.pages for role in page.allowed_roles if role not in role_names]
        if unknown_permission_roles or unknown_page_roles:
            raise ValueError("permissions and page access rules must reference existing roles")
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

