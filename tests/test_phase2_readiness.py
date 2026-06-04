from pathlib import Path

import pytest
from pydantic import ValidationError

from compiler.architecture_planner import plan_architecture
from compiler.contracts import AppSpec, ArchitectureManifest, BusinessRule, Page
from compiler.intent_extractor import extract_intent


def test_every_architecture_element_has_traceability(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    elements = (
        *manifest.entities,
        *manifest.user_flows,
        *manifest.pages,
        *manifest.roles,
        *manifest.permissions,
        *manifest.business_rules,
        *manifest.integrations,
    )

    assert elements
    assert all(element.source_intent_fields for element in elements)


def test_roles_pages_and_business_rules_are_cross_referenced(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    role_names = {role.name for role in manifest.roles}
    flow_names = {flow.name for flow in manifest.user_flows}
    entity_names = {entity.name for entity in manifest.entities}

    assert all(any(permission.role == role.name for permission in manifest.permissions) for role in manifest.roles)
    assert all(page.flow_names and set(page.flow_names) <= flow_names for page in manifest.pages)
    assert all(
        set(rule.referenced_roles) <= role_names and set(rule.referenced_entities) <= entity_names
        for rule in manifest.business_rules
    )
    assert all(rule.referenced_roles or rule.referenced_entities for rule in manifest.business_rules)


def test_integrations_are_reusable_for_api_generation(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)

    assert manifest.integrations
    assert all(integration.capabilities for integration in manifest.integrations)
    assert all(integration.api_base_path for integration in manifest.integrations)


def test_architecture_manifest_has_phase3_schema_inputs_without_prompt_text(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)

    assert manifest.pages and manifest.user_flows
    assert manifest.entities and all(entity.fields for entity in manifest.entities)
    assert manifest.permissions and manifest.roles
    assert manifest.business_rules


def test_app_spec_remains_future_single_source_of_truth() -> None:
    expected_fields = {
        "application_type",
        "entities",
        "pages",
        "api_endpoints",
        "database_tables",
        "auth_policies",
        "ui_components",
        "business_rules",
        "integrations",
    }

    assert expected_fields <= set(AppSpec.model_fields)


def test_manifest_rejects_page_without_existing_flow(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    broken_pages = tuple(
        Page(
            name=page.name,
            route=page.route,
            allowed_roles=page.allowed_roles,
            flow_names=(),
            source_intent_fields=page.source_intent_fields,
            rationale=page.rationale,
        )
        for page in manifest.pages
    )

    with pytest.raises(ValidationError, match="every page must reference"):
        ArchitectureManifest.model_validate(manifest.model_dump() | {"pages": broken_pages})


def test_manifest_rejects_business_rule_without_existing_entity_or_role(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    broken_rules = tuple(
        BusinessRule(
            id=rule.id,
            description=rule.description,
            applies_to=rule.applies_to,
            referenced_entities=("MissingEntity",),
            referenced_roles=(),
            source_intent_fields=rule.source_intent_fields,
            rationale=rule.rationale,
        )
        for rule in manifest.business_rules
    )

    with pytest.raises(ValidationError, match="business rules must reference"):
        ArchitectureManifest.model_validate(manifest.model_dump() | {"business_rules": broken_rules})


def _manifest(tmp_path: Path) -> ArchitectureManifest:
    intent = extract_intent(
        "Build a CRM with contacts, dashboards, admin and user roles, Stripe payments, free and premium plans.",
        log_dir=tmp_path,
    )
    return plan_architecture(intent, log_dir=tmp_path)

