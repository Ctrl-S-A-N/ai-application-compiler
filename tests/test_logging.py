from pathlib import Path

import pytest

from compiler.contracts import CompilerStage, StageExecutionLog
from compiler.logging import read_stage_log, stage_execution


def test_stage_execution_writes_success_log(tmp_path: Path) -> None:
    with stage_execution(CompilerStage.INTENT_EXTRACTION, log_dir=tmp_path) as validation_errors:
        assert validation_errors == []

    log = read_stage_log(tmp_path / "intent_extraction.json")

    assert log.stage == CompilerStage.INTENT_EXTRACTION
    assert log.success_status is True
    assert log.validation_errors == ()
    assert log.repair_attempts == 0
    assert log.latency_ms >= 0


def test_stage_execution_writes_validation_failure_log(tmp_path: Path) -> None:
    with stage_execution(CompilerStage.VALIDATION, log_dir=tmp_path) as validation_errors:
        validation_errors.append("missing role mapping")

    log = read_stage_log(tmp_path / "validation.json")

    assert log.success_status is False
    assert log.validation_errors == ("missing role mapping",)


def test_stage_execution_writes_exception_log(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        with stage_execution(CompilerStage.ARCHITECTURE_PLANNING, log_dir=tmp_path):
            raise RuntimeError("planner failed")

    log: StageExecutionLog = read_stage_log(tmp_path / "architecture_planning.json")

    assert log.success_status is False
    assert log.validation_errors == ("planner failed",)

