from __future__ import annotations

from pathlib import Path

from compiler.contracts import (
    AppSpec,
    ArchitectureManifest,
    CompilerStage,
    UIComponentSchema,
    UIFormSchema,
    UILayout,
    UINavigationItem,
    UIPageSchema,
    UIRoleVisibility,
    UISchema,
)
from compiler.logging import DEFAULT_LOG_DIR, stage_execution


def generate_ui_schema(
    architecture: ArchitectureManifest,
    app_spec: AppSpec,
    log_dir: Path = DEFAULT_LOG_DIR,
) -> UISchema:
    with stage_execution(CompilerStage.UI_SCHEMA_GENERATION, log_dir=log_dir) as validation_errors:
        try:
            schema = _generate_ui_schema(architecture, app_spec)
            UISchema.model_validate(schema.model_dump())
            return schema
        except Exception as exc:
            validation_errors.append(str(exc))
            raise


def _generate_ui_schema(architecture: ArchitectureManifest, app_spec: AppSpec) -> UISchema:
    layouts = (
        UILayout(
            name="default_app_layout",
            regions=("header", "sidebar", "main"),
            source_intent_fields=("pages", "roles"),
            rationale="A stable application layout supports navigation, role-aware menus, and page content.",
        ),
        UILayout(
            name="entity_management_layout",
            regions=("header", "sidebar", "main", "form_panel"),
            source_intent_fields=("entities", "pages"),
            rationale="Entity pages need a form region in addition to the standard application shell.",
        ),
    )
    components: list[UIComponentSchema] = []
    forms: list[UIFormSchema] = []
    navigation: list[UINavigationItem] = []
    ui_pages: list[UIPageSchema] = []

    for page in architecture.pages:
        entity = _entity_for_page(page.route, architecture)
        layout = "entity_management_layout" if entity else "default_app_layout"
        nav_id = _stable_id("nav", page.route)
        navigation.append(
            UINavigationItem(
                id=nav_id,
                label=page.name,
                route=page.route,
                allowed_roles=page.allowed_roles,
                source_intent_fields=page.source_intent_fields,
                rationale=f"{page.name} is navigable for its declared role visibility.",
            )
        )
        component_ids = [_stable_id("component", page.route, "shell")]
        components.append(
            UIComponentSchema(
                id=component_ids[0],
                component_type="page_shell",
                page_route=page.route,
                bound_entity=entity.name if entity else None,
                bound_fields=tuple(field.name for field in entity.fields) if entity else (),
                source_intent_fields=page.source_intent_fields,
                rationale=f"{page.name} needs a shell component for deterministic rendering.",
            )
        )
        form_ids: tuple[str, ...] = ()
        if entity:
            form_id = _stable_id("form", page.route, entity.name)
            form_ids = (form_id,)
            forms.append(
                UIFormSchema(
                    id=form_id,
                    page_route=page.route,
                    entity=entity.name,
                    fields=tuple(field.name for field in entity.fields if field.name != "id"),
                    submit_action=f"create:{entity.name}",
                    source_intent_fields=("entities", "permissions"),
                    rationale=f"{entity.name} fields become a deterministic create form for the page.",
                )
            )
        ui_pages.append(
            UIPageSchema(
                name=page.name,
                route=page.route,
                layout=layout,
                component_ids=tuple(component_ids),
                form_ids=form_ids,
                navigation_item_ids=(nav_id,),
                role_visibility=page.allowed_roles,
                source_intent_fields=page.source_intent_fields,
                rationale=f"{page.name} maps architecture page access to UI schema visibility.",
            )
        )

    role_visibility = tuple(
        UIRoleVisibility(
            role=role.name,
            page_routes=tuple(page.route for page in architecture.pages if role.name in page.allowed_roles),
            source_intent_fields=role.source_intent_fields,
            rationale=f"{role.name} visibility is derived from page allowed_roles.",
        )
        for role in architecture.roles
    )
    return UISchema(
        pages=tuple(ui_pages),
        layouts=layouts,
        components=tuple(components),
        forms=tuple(forms),
        navigation=tuple(navigation),
        role_visibility=role_visibility,
        source_intent_fields=("pages", "entities", "roles"),
        rationale="The UI schema is generated from structured architecture pages, entities, roles, and flows only.",
    )


def _entity_for_page(route: str, architecture: ArchitectureManifest):
    for entity in architecture.entities:
        if route == f"/{_slug(entity.name)}s":
            return entity
    return None


def _stable_id(*parts: str) -> str:
    return "_".join(_slug(part) for part in parts if part)


def _slug(value: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else "_" for character in value)
    return "_".join(part for part in normalized.split("_") if part)
