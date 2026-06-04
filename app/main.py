from fastapi import FastAPI


app = FastAPI(
    title="AI Application Compiler",
    version="0.1.0",
    description="Phase 1 foundation for deterministic application compilation.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

