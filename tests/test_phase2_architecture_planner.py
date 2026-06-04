from pathlib import Path

from compiler.architecture_planner import plan_architecture
from compiler.contracts import ArchitectureManifest, CompilerStage
from compiler.intent_extractor import extract_intent
from compiler.logging import read_stage_log


def test_plan_architecture_generates_required_manifest_sections(tmp_path: Path) -> None:
    intent = extract_intent(
        "Build a CRM with contacts, dashboards, admin and user roles, Stripe billing, free and premium plans.",
        log_dir=tmp_path,
    )

    manifest = plan_architecture(intent, log_dir=tmp_path)

    assert isinstance(manifest, ArchitectureManifest)
    assert manifest.entities
    assert manifest.pages
    assert manifest.user_flows
    assert manifest.roles
    assert manifest.permissions
    assert manifest.business_rules
    assert manifest.integrations
    assert ArchitectureManifest.model_validate(manifest.model_dump()) == manifest
    assert read_stage_log(tmp_path / "architecture_planning.json").stage == CompilerStage.ARCHITECTURE_PLANNING


def test_architecture_permissions_reference_declared_roles(tmp_path: Path) -> None:
    intent = extract_intent("Build a project management tool with tasks for managers and users.", log_dir=tmp_path)

    manifest = plan_architecture(intent, log_dir=tmp_path)
    role_names = {role.name for role in manifest.roles}

    assert all(permission.role in role_names for permission in manifest.permissions)
    assert all(role in role_names for page in manifest.pages for role in page.allowed_roles)


def test_architecture_for_vague_intent_is_provisional_but_valid(tmp_path: Path) -> None:
    intent = extract_intent("Build an app", log_dir=tmp_path)

    manifest = plan_architecture(intent, log_dir=tmp_path)

    assert manifest.entities[0].name == "Record"
    assert any(question.blocking for question in manifest.clarification_questions)
    assert any(assumption.id == "architecture_subject_to_clarification" for assumption in manifest.assumptions)
    assert read_stage_log(tmp_path / "architecture_planning.json").success_status is True


def test_architecture_planning_is_deterministic(tmp_path: Path) -> None:
    intent = extract_intent("Build an LMS with courses, students, teachers, dashboards, and email notifications.", log_dir=tmp_path)

    first = plan_architecture(intent, log_dir=tmp_path)
    second = plan_architecture(intent, log_dir=tmp_path)

    assert first == second
    assert first.model_dump(mode="json") == second.model_dump(mode="json")

