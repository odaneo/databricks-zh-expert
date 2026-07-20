import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.core.config import Settings
from databricks_zh_expert.db.models import ModelCall
from databricks_zh_expert.db.session import Database
from databricks_zh_expert.evaluation.rules import score_case
from databricks_zh_expert.evaluation.types import (
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationDataset,
    EvaluationEvidence,
    EvaluationRunResult,
    EvaluationRunSummary,
)
from databricks_zh_expert.llm.model_registry import ModelAlias, ModelRegistry
from databricks_zh_expert.main import create_app
from databricks_zh_expert.observability.model_trace import (
    JsonlModelTraceSink,
    ModelTraceSink,
    NullModelTraceSink,
)
from databricks_zh_expert.prompts.registry import PromptName, PromptRegistry
from databricks_zh_expert.workspace.context import WorkspaceContextBuilder
from databricks_zh_expert.workspace.registry import WorkspaceRegistry

EVALUATION_OUTPUT_ROOT = Path(".local/evaluations")
EVALUATION_MINIMUM_AVERAGE_SOFT_SCORE = 0.9
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
EvaluationAppFactory = Callable[[Settings, ModelTraceSink], FastAPI]
logger = logging.getLogger(__name__)


class EvaluationRunner:
    def __init__(
        self,
        *,
        dataset: EvaluationDataset,
        settings: Settings,
        output_root: Path = EVALUATION_OUTPUT_ROOT,
        app_factory: EvaluationAppFactory | None = None,
    ) -> None:
        self._dataset = dataset
        self._settings = settings
        self._output_root = output_root
        self._app_factory = app_factory or _default_app_factory

    async def validate(self) -> dict[str, object]:
        issues: list[str] = []
        workspace_registry = WorkspaceRegistry.create_default()
        workspace = workspace_registry.get(self._dataset.workspace_id)
        prompt_registry = PromptRegistry.create_default()
        prompt_registry.validate_all()
        model_registry = ModelRegistry.from_settings(self._settings)
        configured_models = {
            model.value: model_registry.get(model).configured for model in self._dataset.models
        }
        issues.extend(
            f"模型未配置：{model.value}。"
            for model in self._dataset.models
            if not configured_models[model.value]
        )

        context_builder = WorkspaceContextBuilder()
        for case in self._dataset.cases:
            if not case.expected.require_workspace_context:
                continue
            bundle = context_builder.build_for_prompt(
                case.content,
                workspace=workspace,
                prompt_name=case.prompt.value,
            )
            actual_ids = (
                frozenset(selection.unit_id for selection in bundle.selected_units)
                if bundle is not None
                else frozenset()
            )
            missing = tuple(
                unit_id for unit_id in case.expected.workspace_unit_ids if unit_id not in actual_ids
            )
            if missing:
                issues.append(f"{case.id} 缺少 Workspace 单元：{','.join(missing)}。")

        knowledge_status: dict[str, object] = {}
        expert_status: dict[str, object] = {}
        app = self._app_factory(self._settings, NullModelTraceSink())
        try:
            async with app.router.lifespan_context(app):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://evaluation",
                ) as client:
                    knowledge_response = await client.get("/api/knowledge/index/status")
                    expert_response = await client.get("/api/expert-templates/index/status")
                    knowledge_status = _json_object(knowledge_response)
                    expert_status = _json_object(expert_response)
                    if knowledge_response.status_code != 200 or not knowledge_status.get(
                        "queryable"
                    ):
                        issues.append("Databricks 官方知识索引不可查询。")
                    if expert_response.status_code != 200 or not expert_status.get("queryable"):
                        issues.append("专家模板索引不可查询或版本不匹配。")
        except Exception as error:
            issues.append(f"索引预检失败：{type(error).__name__}。")

        return {
            "passed": not issues,
            "dataset_id": self._dataset.dataset_id,
            "dataset_version": self._dataset.version,
            "dataset_hash": self._dataset.source_hash,
            "workspace_id": workspace.workspace_id,
            "workspace_version": workspace.version,
            "workspace_source_hash": workspace.source_hash,
            "models": configured_models,
            "knowledge_index": knowledge_status,
            "expert_template_index": expert_status,
            "issues": issues,
        }

    async def run(
        self,
        *,
        run_id: str,
        model: ModelAlias,
        case_id: str | None = None,
    ) -> EvaluationRunResult:
        _validate_run_id(run_id)
        if model not in self._dataset.models:
            raise ValueError("评估模型不在固定数据集允许范围内。")
        cases = self._select_cases(case_id)
        model_directory = self._output_root / run_id / model.value
        if model_directory.exists() and any(model_directory.iterdir()):
            raise ValueError("该 Run ID 和模型的评估输出已存在，请使用新的 Run ID。")
        model_directory.mkdir(parents=True, exist_ok=True)

        model_registry = ModelRegistry.from_settings(self._settings)
        if not model_registry.get(model).configured:
            raise ValueError(f"模型未配置 API Key：{model.value}。")

        trace_path = model_directory / "trace.jsonl"
        app = self._app_factory(self._settings, JsonlModelTraceSink(trace_path))
        workspace = WorkspaceRegistry.create_default().get(self._dataset.workspace_id)
        started_at = datetime.now(UTC)
        results: list[EvaluationCaseResult] = []
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://evaluation",
                timeout=None,
            ) as client:
                for index, case in enumerate(cases, start=1):
                    logger.info(
                        "端到端评估 Case 开始：%d/%d %s model=%s",
                        index,
                        len(cases),
                        case.id,
                        model.value,
                    )
                    evidence = await self._execute_case(
                        app=app,
                        client=client,
                        trace_path=trace_path,
                        run_id=run_id,
                        model=model,
                        case=case,
                    )
                    result = score_case(case, evidence)
                    results.append(result)
                    logger.info(
                        "端到端评估 Case 完成：%d/%d %s hard=%s soft=%.2f fallback=%s",
                        index,
                        len(cases),
                        case.id,
                        result.hard_passed,
                        result.soft_score,
                        result.fallback_used,
                    )

        completed_at = datetime.now(UTC)
        frozen_results = tuple(results)
        case_count = len(frozen_results)
        passed_count = sum(case.automated_passed for case in frozen_results)
        summary = EvaluationRunSummary(
            case_count=case_count,
            passed_count=passed_count,
            failed_count=case_count - passed_count,
            fallback_count=sum(case.fallback_used for case in frozen_results),
            hard_pass_rate=(
                round(sum(case.hard_passed for case in frozen_results) / case_count, 4)
                if case_count
                else 0
            ),
            average_soft_score=(
                round(sum(case.soft_score for case in frozen_results) / case_count, 4)
                if case_count
                else 0
            ),
            prompt_tokens=sum(case.prompt_tokens for case in frozen_results),
            completion_tokens=sum(case.completion_tokens for case in frozen_results),
            latency_ms=sum(case.latency_ms for case in frozen_results),
        )
        return EvaluationRunResult(
            run_id=run_id,
            dataset_id=self._dataset.dataset_id,
            dataset_version=self._dataset.version,
            dataset_hash=self._dataset.source_hash,
            model=model,
            workspace_id=workspace.workspace_id,
            workspace_version=workspace.version,
            workspace_source_hash=workspace.source_hash,
            started_at=started_at,
            completed_at=completed_at,
            automated_passed=_run_gate_passed(summary),
            summary=summary,
            cases=frozen_results,
        )

    def _select_cases(self, case_id: str | None) -> tuple[EvaluationCase, ...]:
        if case_id is None:
            return self._dataset.cases
        matches = tuple(case for case in self._dataset.cases if case.id == case_id)
        if not matches:
            raise ValueError("端到端评估 Case 不存在。")
        return matches

    async def _execute_case(
        self,
        *,
        app: FastAPI,
        client: AsyncClient,
        trace_path: Path,
        run_id: str,
        model: ModelAlias,
        case: EvaluationCase,
    ) -> EvaluationEvidence:
        title = f"[Eval {run_id}] {case.id} [{model.value}]"
        session_response = await client.post(
            "/api/chat/sessions",
            json={
                "title": title,
                "expert_profile": self._dataset.expert_profile,
                "workspace_id": self._dataset.workspace_id,
            },
        )
        session_payload = _json_object(session_response)
        session_id = _optional_uuid(session_payload.get("id"))
        if session_id is None:
            return _empty_evidence(
                model=model,
                status=session_response.status_code,
                payload=session_payload,
            )

        response = await client.post(
            f"/api/chat/sessions/{session_id}/messages",
            json={
                "content": case.content,
                "model": model.value,
                "prompt": case.prompt.value,
            },
        )
        payload = _json_object(response)
        database = cast(Database, app.state.database)
        async with database.session_factory() as session:
            model_calls = tuple(
                (
                    await session.scalars(
                        select(ModelCall)
                        .where(ModelCall.session_id == session_id)
                        .order_by(ModelCall.attempt_number.asc(), ModelCall.created_at.asc())
                    )
                ).all()
            )
        trace_ids = _trace_ids(trace_path, session_id)
        return _build_evidence(
            model=model,
            status=response.status_code,
            payload=payload,
            session_id=session_id,
            model_calls=model_calls,
            trace_ids=trace_ids,
        )


def _default_app_factory(settings: Settings, trace_sink: ModelTraceSink) -> FastAPI:
    return create_app(settings=settings, model_trace_sink=trace_sink)


def _build_evidence(
    *,
    model: ModelAlias,
    status: int,
    payload: dict[str, Any],
    session_id: UUID,
    model_calls: tuple[ModelCall, ...],
    trace_ids: tuple[UUID, ...],
) -> EvaluationEvidence:
    successful = next((item for item in reversed(model_calls) if item.success), None)
    selected = successful or (model_calls[-1] if model_calls else None)
    assistant = _mapping(payload.get("assistant_message"))
    artifact = _mapping(payload.get("artifact"))
    citations = assistant.get("source_citations")
    citation_urls = (
        tuple(
            str(item.get("url")) for item in citations if isinstance(item, dict) and item.get("url")
        )
        if isinstance(citations, list)
        else ()
    )
    workspace_context = selected.workspace_context if selected is not None else None
    workspace_items = tuple(item for item in workspace_context or [] if isinstance(item, dict))
    error_code, error_message = _error_details(payload, selected)
    used_model = _model_alias(payload.get("used_model"))
    if used_model is None and selected is not None:
        used_model = _model_alias(selected.model_alias)
    return EvaluationEvidence(
        http_status=status,
        requested_model=model,
        used_model=used_model,
        fallback_used=(
            bool(payload.get("fallback_used"))
            or len(model_calls) > 1
            or (used_model is not None and used_model is not model)
        ),
        attempt_count=len(model_calls),
        prompt_name=_prompt_name(payload.get("prompt_name"))
        or _prompt_name(selected.prompt_name if selected is not None else None),
        prompt_version=(
            str(payload.get("prompt_version"))
            if payload.get("prompt_version") is not None
            else selected.prompt_version
            if selected is not None
            else None
        ),
        artifact_type=_artifact_type(artifact.get("type"))
        or _artifact_type(selected.artifact_type if selected is not None else None),
        project_fact_status=_project_fact_status(
            artifact.get("project_fact_status")
            if artifact
            else selected.project_fact_status
            if selected is not None
            else None
        ),
        assistant_content=str(assistant.get("content") or ""),
        citation_urls=citation_urls,
        model_call_ids=tuple(item.id for item in model_calls),
        trace_model_call_ids=trace_ids,
        model_call_success=successful is not None,
        artifact_valid=selected.artifact_valid if selected is not None else None,
        workspace_id=selected.workspace_id if selected is not None else None,
        workspace_version=selected.workspace_version if selected is not None else None,
        workspace_source_hash=(selected.workspace_source_hash if selected is not None else None),
        workspace_unit_ids=tuple(
            str(item["unit_id"]) for item in workspace_items if item.get("unit_id")
        ),
        workspace_source_paths=tuple(
            dict.fromkeys(
                str(item["source_path"]) for item in workspace_items if item.get("source_path")
            )
        ),
        prompt_tokens=sum(item.prompt_tokens or 0 for item in model_calls),
        completion_tokens=sum(item.completion_tokens or 0 for item in model_calls),
        latency_ms=sum(item.latency_ms for item in model_calls),
        error_code=error_code,
        error_message=error_message,
        session_id=session_id,
    )


def _empty_evidence(
    *, model: ModelAlias, status: int, payload: dict[str, Any]
) -> EvaluationEvidence:
    error_code, error_message = _error_details(payload, None)
    return EvaluationEvidence(
        http_status=status,
        requested_model=model,
        used_model=None,
        fallback_used=False,
        attempt_count=0,
        prompt_name=None,
        prompt_version=None,
        artifact_type=None,
        project_fact_status=None,
        assistant_content="",
        citation_urls=(),
        model_call_ids=(),
        trace_model_call_ids=(),
        model_call_success=False,
        artifact_valid=None,
        workspace_id=None,
        workspace_version=None,
        workspace_source_hash=None,
        workspace_unit_ids=(),
        workspace_source_paths=(),
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=0,
        error_code=error_code,
        error_message=error_message,
    )


def _trace_ids(path: Path, session_id: UUID) -> tuple[UUID, ...]:
    if not path.is_file():
        return ()
    ids: list[UUID] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
            trace = payload["trace"]
            if trace["session_id"] == str(session_id):
                ids.append(UUID(trace["model_call_id"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return tuple(ids)


def _json_object(response: Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value is not None else None
    except ValueError:
        return None


def _model_alias(value: object) -> ModelAlias | None:
    try:
        return ModelAlias(str(value)) if value is not None else None
    except ValueError:
        return None


def _prompt_name(value: object) -> PromptName | None:
    try:
        return PromptName(str(value)) if value is not None else None
    except ValueError:
        return None


def _artifact_type(value: object) -> ArtifactType | None:
    try:
        return ArtifactType(str(value)) if value is not None else None
    except ValueError:
        return None


def _project_fact_status(value: object) -> Literal["proposal"] | None:
    return "proposal" if value == "proposal" else None


def _error_details(
    payload: dict[str, Any],
    selected: ModelCall | None,
) -> tuple[str | None, str | None]:
    code = payload.get("code")
    message = payload.get("message")
    return (
        str(code) if code is not None else selected.error_code if selected is not None else None,
        str(message)
        if message is not None
        else selected.error_message
        if selected is not None
        else None,
    )


def _validate_run_id(run_id: str) -> None:
    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("Run ID 只能包含字母、数字、点、下划线和连字符。")


def _run_gate_passed(summary: EvaluationRunSummary) -> bool:
    return (
        summary.case_count > 0
        and summary.hard_pass_rate == 1.0
        and summary.average_soft_score >= EVALUATION_MINIMUM_AVERAGE_SOFT_SCORE
    )
