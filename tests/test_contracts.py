import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from compiler.contracts import (
    ApplicationType,
    ArchitectureDecisionLog,
    ArchitectureManifest,
    Entity,
    EntityField,
    FieldType,
    Integration,
    IntentIR,
    IntentEntity,
    Page,
    Permission,
    Role,
    json_schema_for,
)


def test_intent_ir_requires_rationale_and_rejects_unknown_fields() -> None:
    intent = IntentIR(
        application_type=ApplicationType.CRM,
        features=(),
        entities=(IntentEntity(name="Contact", rationale="Contacts are the primary CRM records."),),
        integrations=(Integration(name="Stripe", provider="stripe", required=False, rationale="Payments may be optional."),),
        roles=(Role(name="admin", rationale="Administrators manage the application."),),
        plans=(),
        rationale="CRM is the closest supported application type.",
    )

    assert intent.application_type == ApplicationType.CRM
    assert intent.roles[0].name == "admin"
    assert intent.entities[0].name == "Contact"
    assert intent.integrations[0].provider == "stripe"

    with pytest.raises(ValidationError):
        IntentIR.model_validate(
            {
                "application_type": "CRM",
                "features": [],
                "roles": [],
                "entities": [],
                "integrations": [],
                "plans": [],
                "rationale": "Valid rationale.",
                "unexpected": "rejected",
            }
        )


def test_entity_field_names_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="entity field names must be unique"):
        Entity(
            name="Contact",
            rationale="Contacts are core CRM records.",
            fields=(
                EntityField(name="email", field_type=FieldType.EMAIL, rationale="Email identifies the contact."),
                EntityField(name="email", field_type=FieldType.STRING, rationale="Duplicate should fail."),
            ),
        )


def test_architecture_manifest_validates_role_references() -> None:
    with pytest.raises(ValidationError, match="existing roles"):
        ArchitectureManifest(
            roles=(Role(name="admin", rationale="Administrators can manage records."),),
            pages=(Page(name="Dashboard", route="/dashboard", allowed_roles=("ghost",), rationale="Dashboard is protected."),),
            permissions=(Permission(role="admin", action="read", resource="dashboard", rationale="Admins can read dashboards."),),
            rationale="The architecture maps access rules to declared roles.",
        )


def test_json_schema_for_exports_contract_schema() -> None:
    schema = json_schema_for(IntentIR)

    assert schema["title"] == "IntentIR"
    assert "application_type" in schema["properties"]
    assert "entities" in schema["properties"]
    assert "integrations" in schema["properties"]
    assert schema["additionalProperties"] is False


def test_architecture_decision_log_file_matches_contract() -> None:
    payload = json.loads(Path("architecture_decisions.json").read_text(encoding="utf-8"))
    decision_log = ArchitectureDecisionLog.model_validate(payload)

    assert len(decision_log.decisions) >= 1
    assert all(decision.rationale for decision in decision_log.decisions)
