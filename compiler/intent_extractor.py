from __future__ import annotations

import re
from pathlib import Path
from typing import TypeVar

from compiler.contracts import (
    ApplicationType,
    Assumption,
    ClarificationQuestion,
    CompilerStage,
    Feature,
    Integration,
    IntentEntity,
    IntentIR,
    Plan,
    Role,
)
from compiler.logging import DEFAULT_LOG_DIR, stage_execution


APPLICATION_KEYWORDS: tuple[tuple[ApplicationType, tuple[str, ...]], ...] = (
    (ApplicationType.CRM, ("crm", "contact", "lead", "customer relationship")),
    (ApplicationType.PROJECT_MANAGEMENT, ("project management", "task", "kanban", "sprint")),
    (ApplicationType.MARKETPLACE, ("marketplace", "seller", "buyer", "vendor")),
    (ApplicationType.LMS, ("course", "learning", "lesson", "student", "teacher")),
    (ApplicationType.ANALYTICS, ("analytics", "dashboard", "metric", "reporting")),
    (ApplicationType.INTERNAL_TOOL, ("internal tool", "back office", "admin panel")),
    (ApplicationType.SAAS, ("saas", "subscription", "tenant", "workspace")),
)

FEATURE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("authentication", ("auth", "login", "sign in", "signup", "password", "sso")),
    ("contacts", ("contact", "lead", "customer")),
    ("payments", ("payment", "stripe", "billing", "subscription", "invoice")),
    ("dashboards", ("dashboard", "analytics", "metrics", "reports")),
    ("tasks", ("task", "kanban", "todo", "sprint")),
    ("courses", ("course", "lesson", "module", "quiz")),
    ("notifications", ("notification", "email", "sms", "alert")),
    ("file_uploads", ("upload", "attachment", "document", "file")),
    ("search", ("search", "filter")),
)

ROLE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("admin", ("admin", "administrator", "owner")),
    ("user", ("user", "member", "customer")),
    ("manager", ("manager", "operator")),
    ("seller", ("seller", "vendor")),
    ("buyer", ("buyer", "shopper")),
    ("student", ("student", "learner")),
    ("teacher", ("teacher", "instructor")),
)

PLAN_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("free", ("free", "trial")),
    ("premium", ("premium", "paid", "pro")),
    ("enterprise", ("enterprise", "team plan")),
)

ENTITY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Contact", ("contact", "lead", "customer")),
    ("Account", ("account", "company")),
    ("Deal", ("deal", "opportunity", "pipeline")),
    ("Task", ("task", "todo", "kanban")),
    ("Project", ("project", "sprint")),
    ("Course", ("course", "lesson")),
    ("Enrollment", ("enrollment", "student")),
    ("Product", ("product", "listing")),
    ("Order", ("order", "checkout", "purchase")),
    ("Invoice", ("invoice", "billing", "subscription")),
    ("Report", ("report", "dashboard", "metric")),
)

INTEGRATION_KEYWORDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Stripe", "stripe", ("stripe", "payment", "billing", "subscription")),
    ("SendGrid", "sendgrid", ("sendgrid", "email")),
    ("Twilio", "twilio", ("twilio", "sms")),
    ("Slack", "slack", ("slack",)),
    ("Google OAuth", "google", ("google login", "google oauth", "gmail")),
)

NEGATED_AUTH_PATTERNS = (
    r"\bno\s+(auth|authentication|login|sign\s*in)\b",
    r"\bwithout\s+(auth|authentication|login|sign\s*in)\b",
)

AUTH_REQUIRED_PATTERNS = (
    r"\b(auth|authentication|login|sign\s*in|signup|password|sso)\b",
    r"\badmin\b",
    r"\brole[s]?\b",
)

VAGUE_PROMPTS = {"app", "make an app", "build an app", "website", "saas", "tool"}
NamedItem = TypeVar("NamedItem")


def extract_intent(requirements: str, log_dir: Path = DEFAULT_LOG_DIR) -> IntentIR:
    with stage_execution(CompilerStage.INTENT_EXTRACTION, log_dir=log_dir) as validation_errors:
        try:
            intent = _extract_intent(requirements)
            IntentIR.model_validate(intent.model_dump())
            return intent
        except Exception as exc:
            validation_errors.append(str(exc))
            raise


def _extract_intent(requirements: str) -> IntentIR:
    prompt = requirements.strip()
    normalized = _normalize(prompt)
    assumptions: list[Assumption] = []
    clarifications: list[ClarificationQuestion] = []

    if not prompt:
        clarifications.append(
            ClarificationQuestion(
                id="clarify_application_goal",
                question="What application should be compiled?",
                blocking=True,
                rationale="An empty request has no reliable application domain, users, or features.",
            )
        )
        assumptions.append(
            Assumption(
                id="assume_custom_app_until_clarified",
                description="Treat the request as a custom application until the user supplies requirements.",
                rationale="A valid IntentIR is still needed for deterministic downstream handling.",
            )
        )
        return IntentIR(
            application_type=ApplicationType.CUSTOM,
            assumptions=tuple(assumptions),
            clarification_questions=tuple(clarifications),
            rationale="The prompt was empty, so the safest valid intent is a custom application requiring clarification.",
        )

    application_type = _detect_application_type(normalized)
    if application_type is ApplicationType.CUSTOM:
        assumptions.append(
            Assumption(
                id="assume_custom_application_type",
                description="Use a custom application type because no supported SaaS domain was explicit.",
                rationale="The extractor must produce a valid structured intent without inventing a domain.",
            )
        )

    if normalized in VAGUE_PROMPTS or len(normalized.split()) <= 3:
        clarifications.append(
            ClarificationQuestion(
                id="clarify_core_workflow",
                question="What core workflow, users, and data should the application support?",
                blocking=True,
                rationale="The request is too vague to plan reliable entities and permissions.",
            )
        )

    if _has_auth_conflict(normalized):
        clarifications.append(
            ClarificationQuestion(
                id="clarify_auth_conflict",
                question="Should the application include authentication and role-based access?",
                blocking=True,
                rationale="The prompt both rejects authentication and asks for role or login behavior.",
            )
        )

    features = _detect_features(normalized)
    roles = _detect_roles(normalized, features)
    entities = _detect_entities(normalized, application_type, features)
    integrations = _detect_integrations(normalized)
    plans = _detect_plans(normalized)

    if not features:
        assumptions.append(
            Assumption(
                id="assume_crud_feature_set",
                description="Start with basic create, read, update, and delete workflows for the detected entities.",
                rationale="The prompt names too few explicit features, but CRUD is the minimum useful SaaS scaffold behavior.",
            )
        )
        features.append(Feature(name="crud", source_intent_fields=("assumptions",), rationale="CRUD is assumed as the minimum executable application behavior."))

    if not roles:
        assumptions.append(
            Assumption(
                id="assume_admin_and_user_roles",
                description="Use admin and user roles unless the prompt defines a different role structure.",
                rationale="Most SaaS applications need at least privileged and standard access levels.",
            )
        )
        roles.extend(
            [
                Role(name="admin", source_intent_fields=("assumptions",), rationale="An admin role is needed for privileged management actions."),
                Role(name="user", source_intent_fields=("assumptions",), rationale="A user role is needed for standard product access."),
            ]
        )

    return IntentIR(
        application_type=application_type,
        features=tuple(_dedupe_by_name(features)),
        roles=tuple(_dedupe_by_name(roles)),
        entities=tuple(_dedupe_by_name(entities)),
        integrations=tuple(_dedupe_by_name(integrations)),
        plans=tuple(_dedupe_by_name(plans)),
        assumptions=tuple(assumptions),
        clarification_questions=tuple(clarifications),
        rationale="The intent is derived deterministically from explicit keywords, conservative defaults, and critical ambiguity checks.",
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _detect_application_type(normalized: str) -> ApplicationType:
    for application_type, keywords in APPLICATION_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return application_type
    return ApplicationType.CUSTOM


def _detect_features(normalized: str) -> list[Feature]:
    return [
        Feature(name=name, source_intent_fields=("requirements",), rationale=f"The prompt references {name} capability keywords.")
        for name, keywords in FEATURE_KEYWORDS
        if any(keyword in normalized for keyword in keywords)
    ]


def _detect_roles(normalized: str, features: list[Feature]) -> list[Role]:
    roles = [
        Role(name=name, source_intent_fields=("requirements", "roles"), rationale=f"The prompt references the {name} role.")
        for name, keywords in ROLE_KEYWORDS
        if any(keyword in normalized for keyword in keywords)
    ]
    if any(feature.name == "authentication" for feature in features) and not roles:
        roles.append(Role(name="user", source_intent_fields=("features",), rationale="Authentication implies at least a standard authenticated user role."))
    return roles


def _detect_plans(normalized: str) -> list[Plan]:
    return [
        Plan(name=name, source_intent_fields=("requirements", "plans"), rationale=f"The prompt references the {name} plan.")
        for name, keywords in PLAN_KEYWORDS
        if any(keyword in normalized for keyword in keywords)
    ]


def _detect_entities(
    normalized: str,
    application_type: ApplicationType,
    features: list[Feature],
) -> list[IntentEntity]:
    entities = [
        IntentEntity(name=name, source_intent_fields=("requirements", "entities"), rationale=f"The prompt references {name.lower()} data.")
        for name, keywords in ENTITY_KEYWORDS
        if any(keyword in normalized for keyword in keywords)
    ]
    if not entities and application_type is ApplicationType.CRM:
        entities.append(IntentEntity(name="Contact", source_intent_fields=("application_type",), rationale="CRM applications require contacts as a core data object."))
    if not entities and any(feature.name == "tasks" for feature in features):
        entities.append(IntentEntity(name="Task", source_intent_fields=("features",), rationale="Task features require a task data object."))
    return entities


def _detect_integrations(normalized: str) -> list[Integration]:
    return [
        Integration(
            name=name,
            provider=provider,
            required=provider in normalized,
            capabilities=_integration_capabilities(provider),
            api_base_path=f"/integrations/{provider}",
            source_intent_fields=("requirements", "integrations"),
            rationale=f"The prompt references {name} integration keywords.",
        )
        for name, provider, keywords in INTEGRATION_KEYWORDS
        if any(keyword in normalized for keyword in keywords)
    ]


def _has_auth_conflict(normalized: str) -> bool:
    rejects_auth = any(re.search(pattern, normalized) for pattern in NEGATED_AUTH_PATTERNS)
    requires_auth = any(re.search(pattern, normalized) for pattern in AUTH_REQUIRED_PATTERNS)
    return rejects_auth and requires_auth


def _integration_capabilities(provider: str) -> tuple[str, ...]:
    capabilities_by_provider = {
        "stripe": ("payments", "webhooks"),
        "sendgrid": ("email",),
        "twilio": ("sms",),
        "slack": ("notifications",),
        "google": ("oauth",),
    }
    return capabilities_by_provider.get(provider, ("external_api",))


def _dedupe_by_name(items: list[NamedItem]) -> list[NamedItem]:
    seen: set[str] = set()
    deduped: list[NamedItem] = []
    for item in items:
        name = getattr(item, "name")
        if name not in seen:
            seen.add(name)
            deduped.append(item)
    return deduped
