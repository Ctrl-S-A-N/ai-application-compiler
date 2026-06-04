# AI Application Compiler

Phase 1 establishes the production foundation for a compiler-style pipeline:

```text
Natural Language
  -> IntentIR
  -> ArchitectureIR
  -> AppSpec
  -> Schema Generation
  -> Validation
  -> Repair
  -> Runtime Generation
  -> Executable Application
```

## Architecture

The current implementation contains strict Pydantic contracts for:

- `IntentIR`
- `ArchitectureManifest`
- `AppSpec`
- `StageExecutionLog`
- `ArchitectureDecisionLog`

Every generated artifact has a required `rationale` field. Models forbid unknown fields, validate references where Phase 1 owns the contract, and expose JSON Schema through `json_schema_for(...)`.

Phase 2 adds deterministic, independently testable compiler stages:

- `extract_intent(...)` converts natural language requirements into `IntentIR`.
- `plan_architecture(...)` converts `IntentIR` into `ArchitectureManifest`.
- Both stages write JSON execution logs and return Pydantic models only.
- Vague, conflicting, and underspecified prompts are represented with structured assumptions and clarification questions.

Phase 3 adds isolated schema generators:

- `generate_ui_schema(...)` emits `UISchema`.
- `generate_api_schema(...)` emits `APISchema`.
- `generate_database_schema(...)` emits `DatabaseSchema`.
- `generate_auth_schema(...)` emits `AuthSchema`.
- Each generator consumes `ArchitectureManifest` and `AppSpec`, writes its own execution log, and does not read the original prompt.

```text
app/
  main.py                  FastAPI health surface
compiler/
  contracts.py             Strict IR, spec, and log contracts
  logging.py               JSON execution logs for compiler stages
  intent_extractor.py      Deterministic natural language to IntentIR stage
  architecture_planner.py  Deterministic IntentIR to ArchitectureManifest stage
  schema_generators/       Independent UI/API/DB/Auth schema generators
schemas/
  README.md                Schema contract policy
logs/
  runtime stage logs
tests/
  Phase 1 unit tests
```

## Validation Strategy

Phase 1 validation is contract-level:

- Unknown fields are rejected.
- Required rationale fields are enforced.
- Entity field names must be unique.
- Page access rules and permissions must reference declared roles.
- Stage logs require monotonic timestamps and non-negative latency.

Later phases will add JSON validity, schema validity, type safety, UI-to-API, API-to-DB, auth-to-UI, and business-rule cross-layer checks.

## Repair Strategy

Repair is not implemented in Phase 1. The architecture reserves a dedicated `repair_engine` module and records `repair_attempts` in every stage log so Phase 5 can add targeted layer-specific repairs without changing the logging contract.

## Runtime Generation

Runtime generation is not implemented in Phase 1. The `runtime_generator` module is reserved for Phase 6, where it will emit runnable FastAPI, SQLite, React, and Docker artifacts from the validated `AppSpec`.

## Tradeoffs

This phase prioritizes deterministic contracts and testability over feature breadth. The result is slower initial delivery of visible application behavior, but it reduces downstream ambiguity, retry loops, and invalid generated artifacts.

## Testing

Install development dependencies, then run:

```powershell
python -m pytest
```
