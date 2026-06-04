# Schema Contracts

Phase 1 defines schema contracts in `compiler/contracts.py`.

The canonical source is Pydantic. JSON Schema is generated from those models through `json_schema_for(...)` so future phases do not maintain duplicate hand-written contracts.

