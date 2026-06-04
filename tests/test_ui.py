"""Phase 7 – Reviewer UI Tests.

Tests the FastAPI compile endpoint for the reviewer frontend to ensure integration functionality.
"""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_api_compile_endpoint():
    response = client.post(
        "/api/compile",
        json={"prompt": "Build a CRM with contacts and users."}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify all expected UI stages are present in the payload
    assert "intent_ir" in data
    assert "architecture" in data
    assert "ui_schema" in data
    assert "api_schema" in data
    assert "db_schema" in data
    assert "auth_schema" in data
    assert "validation_report" in data
    assert "repair_report" in data
    assert "runtime_report" in data
    
    # Basic sanity checks on content
    assert data["intent_ir"]["application_type"] == "CRM"
    assert data["architecture"]["pages"] is not None
    assert data["runtime_report"]["success"] is True
