from pathlib import Path

from compiler.contracts import ApplicationType, CompilerStage, IntentIR
from compiler.intent_extractor import extract_intent
from compiler.logging import read_stage_log


def test_extract_intent_from_complete_crm_prompt(tmp_path: Path) -> None:
    prompt = "Build a CRM with contacts, lead tracking, admin and user roles, Stripe payments, free and premium plans."

    intent = extract_intent(prompt, log_dir=tmp_path)

    assert isinstance(intent, IntentIR)
    assert intent.application_type == ApplicationType.CRM
    assert {feature.name for feature in intent.features} >= {"contacts", "payments"}
    assert {role.name for role in intent.roles} >= {"admin", "user"}
    assert {entity.name for entity in intent.entities} >= {"Contact"}
    assert {integration.provider for integration in intent.integrations} >= {"stripe"}
    assert {plan.name for plan in intent.plans} >= {"free", "premium"}
    assert intent.clarification_questions == ()
    assert read_stage_log(tmp_path / "intent_extraction.json").stage == CompilerStage.INTENT_EXTRACTION


def test_extract_intent_from_vague_prompt_requests_blocking_clarification(tmp_path: Path) -> None:
    intent = extract_intent("Build an app", log_dir=tmp_path)

    assert intent.application_type == ApplicationType.CUSTOM
    assert any(question.blocking for question in intent.clarification_questions)
    assert any(assumption.id == "assume_custom_application_type" for assumption in intent.assumptions)
    assert read_stage_log(tmp_path / "intent_extraction.json").success_status is True


def test_extract_intent_from_empty_prompt_returns_structured_blocking_clarification(tmp_path: Path) -> None:
    intent = extract_intent("", log_dir=tmp_path)

    assert intent.application_type == ApplicationType.CUSTOM
    assert intent.features == ()
    assert any(question.id == "clarify_application_goal" and question.blocking for question in intent.clarification_questions)
    assert IntentIR.model_validate(intent.model_dump()) == intent


def test_extract_intent_from_conflicting_prompt_preserves_conflict(tmp_path: Path) -> None:
    prompt = "Build an admin dashboard with user roles but no login or authentication."

    intent = extract_intent(prompt, log_dir=tmp_path)

    assert any(question.id == "clarify_auth_conflict" for question in intent.clarification_questions)
    assert {role.name for role in intent.roles} >= {"admin", "user"}
    assert IntentIR.model_validate(intent.model_dump()) == intent


def test_extract_intent_from_underspecified_prompt_uses_conservative_assumptions(tmp_path: Path) -> None:
    intent = extract_intent("A subscription SaaS for reports", log_dir=tmp_path)

    assert intent.application_type == ApplicationType.SAAS
    assert {feature.name for feature in intent.features} >= {"dashboards"}
    assert {role.name for role in intent.roles} == {"admin", "user"}
    assert intent.assumptions


def test_intent_extraction_is_deterministic(tmp_path: Path) -> None:
    prompt = "Build a marketplace with sellers, buyers, products, orders, payments, and notifications."

    first = extract_intent(prompt, log_dir=tmp_path)
    second = extract_intent(prompt, log_dir=tmp_path)

    assert first == second
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
