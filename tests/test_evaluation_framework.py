"""Phase 8 – Evaluation Framework tests."""

import json
from pathlib import Path

from evaluation.evaluation_runner import run_evaluation


def test_evaluation_runner_success(tmp_path: Path) -> None:
    dataset_file = tmp_path / "dataset.json"
    output_dir = tmp_path / "eval_output"
    output_dir.mkdir()
    
    # Create minimal dataset
    dataset_data = {
        "realistic": [
            {"id": "test_1", "prompt": "Build a CRM with contacts and admin roles."}
        ],
        "edge_cases": [
            {"id": "test_vague", "prompt": "build an app"}
        ]
    }
    dataset_file.write_text(json.dumps(dataset_data), encoding="utf-8")
    
    report = run_evaluation(dataset_file, output_dir)
    
    assert report["summary"]["total_prompts"] == 2
    assert "success_rate" in report["summary"]
    assert "avg_latency_ms" in report["summary"]
    assert len(report["results"]) == 2
    
    # Check that report is saved
    report_file = output_dir / "evaluation_report.json"
    assert report_file.exists()
    
    saved_report = json.loads(report_file.read_text(encoding="utf-8"))
    assert saved_report == report


def test_evaluation_runner_exception_handling(tmp_path: Path, monkeypatch) -> None:
    dataset_file = tmp_path / "dataset.json"
    output_dir = tmp_path / "eval_output_exc"
    output_dir.mkdir()
    
    dataset_data = {
        "realistic": [
            {"id": "test_err", "prompt": "trigger exception"}
        ]
    }
    dataset_file.write_text(json.dumps(dataset_data), encoding="utf-8")
    
    def mock_extract(*args, **kwargs):
        raise ValueError("Simulated failure")
        
    import evaluation.evaluation_runner
    monkeypatch.setattr(evaluation.evaluation_runner, "extract_intent", mock_extract)
    
    report = run_evaluation(dataset_file, output_dir)
    
    assert report["summary"]["total_prompts"] == 1
    assert report["results"][0]["success"] is False
    assert "Simulated failure" in report["results"][0]["error"]
