from __future__ import annotations

from pathlib import Path

from compiler.contracts import (
    AppSpec,
    ArchitectureManifest,
    CompilerStage,
    DatabaseConstraint,
    DatabaseFieldSchema,
    DatabaseIndex,
    DatabaseRelationship,
    DatabaseSchema,
    DatabaseTableSchema,
)
from compiler.logging import DEFAULT_LOG_DIR, stage_execution


def generate_database_schema(
    architecture: ArchitectureManifest,
    app_spec: AppSpec,
    log_dir: Path = DEFAULT_LOG_DIR,
) -> DatabaseSchema:
    with stage_execution(CompilerStage.DB_SCHEMA_GENERATION, log_dir=log_dir) as validation_errors:
        try:
            schema = _generate_database_schema(architecture, app_spec)
            DatabaseSchema.model_validate(schema.model_dump())
            return schema
        except Exception as exc:
            validation_errors.append(str(exc))
            raise


def _generate_database_schema(architecture: ArchitectureManifest, app_spec: AppSpec) -> DatabaseSchema:
    tables: list[DatabaseTableSchema] = []
    all_fields: list[DatabaseFieldSchema] = []
    constraints: list[DatabaseConstraint] = []
    indexes: list[DatabaseIndex] = []

    for entity in architecture.entities:
        table_name = _table_name(entity.name)
        fields = tuple(
            DatabaseFieldSchema(
                name=field.name,
                field_type=field.field_type,
                nullable=not field.required,
                unique=field.unique,
                source_intent_fields=field.source_intent_fields,
                rationale=f"{field.name} is copied from the architecture entity field contract.",
            )
            for field in entity.fields
        )
        tables.append(
            DatabaseTableSchema(
                name=table_name,
                entity=entity.name,
                fields=fields,
                source_intent_fields=entity.source_intent_fields,
                rationale=f"{entity.name} maps to a deterministic SQLite table.",
            )
        )
        all_fields.extend(fields)
        constraints.append(
            DatabaseConstraint(
                table=table_name,
                constraint_type="primary_key",
                fields=("id",),
                source_intent_fields=entity.source_intent_fields,
                rationale=f"{table_name}.id is the stable primary key.",
            )
        )
        for field in entity.fields:
            if field.required:
                constraints.append(
                    DatabaseConstraint(
                        table=table_name,
                        constraint_type="not_null",
                        fields=(field.name,),
                        source_intent_fields=field.source_intent_fields,
                        rationale=f"{table_name}.{field.name} is required by the architecture field contract.",
                    )
                )
            if field.unique:
                indexes.append(
                    DatabaseIndex(
                        table=table_name,
                        fields=(field.name,),
                        unique=True,
                        source_intent_fields=field.source_intent_fields,
                        rationale=f"{table_name}.{field.name} needs a unique lookup index.",
                    )
                )
        indexes.append(
            DatabaseIndex(
                table=table_name,
                fields=("created_at",),
                unique=False,
                source_intent_fields=entity.source_intent_fields,
                rationale=f"{table_name}.created_at supports deterministic ordering.",
            )
        )

    return DatabaseSchema(
        tables=tuple(tables),
        fields=tuple(all_fields),
        relationships=tuple(_relationships_for(architecture)),
        constraints=tuple(constraints),
        indexes=tuple(indexes),
        source_intent_fields=("entities",),
        rationale="The database schema is generated from structured entities and fields without prompt parsing.",
    )


def _relationships_for(architecture: ArchitectureManifest) -> list[DatabaseRelationship]:
    relationships: list[DatabaseRelationship] = []
    entity_names = {entity.name for entity in architecture.entities}
    if {"Account", "Contact"} <= entity_names:
        relationships.append(
            DatabaseRelationship(
                from_table="contacts",
                to_table="accounts",
                relationship_type="many_to_one",
                source_intent_fields=("entities",),
                rationale="Contacts can belong to an account when both entities exist.",
            )
        )
    if {"Order", "Product"} <= entity_names:
        relationships.append(
            DatabaseRelationship(
                from_table="orders",
                to_table="products",
                relationship_type="many_to_many",
                source_intent_fields=("entities",),
                rationale="Orders can contain products when both entities exist.",
            )
        )
    return relationships


def _table_name(entity_name: str) -> str:
    return f"{_slug(entity_name)}s"


def _slug(value: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else "_" for character in value)
    return "_".join(part for part in normalized.split("_") if part)
