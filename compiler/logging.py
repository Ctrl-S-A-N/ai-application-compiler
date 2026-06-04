from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Iterator

from compiler.contracts import CompilerStage, StageExecutionLog


DEFAULT_LOG_DIR = Path("logs")


def write_stage_log(log: StageExecutionLog, log_dir: Path = DEFAULT_LOG_DIR) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    output_path = log_dir / f"{log.stage.value}.json"
    output_path.write_text(
        log.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return output_path


@contextmanager
def stage_execution(
    stage: CompilerStage,
    log_dir: Path = DEFAULT_LOG_DIR,
    repair_attempts: int = 0,
) -> Iterator[list[str]]:
    start_time = datetime.now(UTC)
    started_at = perf_counter()
    validation_errors: list[str] = []
    success_status = False
    try:
        yield validation_errors
        success_status = not validation_errors
    except Exception as exc:
        validation_errors.append(str(exc))
        raise
    finally:
        end_time = datetime.now(UTC)
        latency_ms = (perf_counter() - started_at) * 1000
        write_stage_log(
            StageExecutionLog(
                stage=stage,
                start_time=start_time,
                end_time=end_time,
                latency_ms=latency_ms,
                validation_errors=tuple(validation_errors),
                repair_attempts=repair_attempts,
                success_status=success_status,
            ),
            log_dir=log_dir,
        )


def read_stage_log(path: Path) -> StageExecutionLog:
    return StageExecutionLog.model_validate(json.loads(path.read_text(encoding="utf-8")))

