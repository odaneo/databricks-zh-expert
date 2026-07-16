import json
from collections.abc import Sequence
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from databricks_zh_expert.expert_templates.cli import (
    ExpertTemplateCliRuntime,
    ExpertTemplateStatusRepository,
    ExpertTemplateSyncRunner,
    run_async,
)
from databricks_zh_expert.expert_templates.context import (
    ExpertTemplateContextNotFoundError,
    ExpertTemplateRetrievalBundle,
    ExpertTemplateSelection,
    SelectionReason,
)
from databricks_zh_expert.expert_templates.evaluation import (
    EXPERT_TEMPLATE_EVALUATION_PATH,
    ExpertTemplateEvaluationCase,
    ExpertTemplateEvaluationDataset,
    ExpertTemplateEvaluationError,
    ExpertTemplateEvaluationResult,
    ExpertTemplateEvaluator,
    load_expert_template_evaluation_set,
)
from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry
from databricks_zh_expert.prompts.registry import PromptName
from databricks_zh_expert.rag.embeddings import EmbeddingResult


@pytest.fixture(scope="module")
def registry() -> ExpertTemplateRegistry:
    return ExpertTemplateRegistry.create_default()


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def embed_query(self, text: str) -> EmbeddingResult:
        self.queries.append(text)
        return EmbeddingResult(index=0, embedding=(0.01,) * 1536)

    async def embed_documents(
        self,
        texts: Sequence[str],
    ) -> tuple[EmbeddingResult, ...]:
        del texts
        raise AssertionError("评估不得调用 embed_documents。")


class FakeRetriever:
    def __init__(
        self,
        responses: dict[str, ExpertTemplateRetrievalBundle | Exception],
    ) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, PromptName, tuple[float, ...]]] = []

    async def retrieve(
        self,
        query: str,
        *,
        query_embedding: Sequence[float],
        profile_id: str,
        prompt_name: PromptName,
    ) -> ExpertTemplateRetrievalBundle:
        self.calls.append((query, profile_id, prompt_name, tuple(query_embedding)))
        response = self.responses[query]
        if isinstance(response, Exception):
            raise response
        return response


class FakeEvaluationRunner:
    def __init__(
        self,
        result: ExpertTemplateEvaluationResult | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.paths: list[Path] = []

    async def evaluate_file(self, path: Path) -> ExpertTemplateEvaluationResult:
        self.paths.append(path)
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("测试未配置评估结果。")
        return self.result


def _selection(
    value: int,
    template_id: str,
    *,
    layer: str = "core",
    reason: SelectionReason = "semantic",
    extends: str | None = None,
) -> ExpertTemplateSelection:
    return ExpertTemplateSelection(
        record_id=UUID(int=value),
        template_id=template_id,
        version="1.0.0",
        name=template_id,
        content_hash=f"{value:064x}",
        layer=layer,
        profile_id=None if layer == "core" else layer,
        rank=value,
        reason=reason,
        extends=extends,
    )


def _bundle(
    query: str,
    profile_id: str,
    *selections: ExpertTemplateSelection,
) -> ExpertTemplateRetrievalBundle:
    return ExpertTemplateRetrievalBundle(
        query=query,
        profile_id=profile_id,
        prompt_name=PromptName.WORKFLOW_DESIGN,
        ranked_candidates=(),
        selected_templates=selections,
        context="测试专家上下文",
        context_token_count=10,
    )


def _case(
    case_id: str,
    query: str,
    *expected_template_ids: str,
    profile: str = "generic",
    forbidden_layers: tuple[str, ...] = ("retail_sales_demo",),
) -> ExpertTemplateEvaluationCase:
    return ExpertTemplateEvaluationCase(
        id=case_id,
        profile=profile,
        prompt=PromptName.WORKFLOW_DESIGN,
        query=query,
        expected_template_ids=expected_template_ids,
        forbidden_layers=forbidden_layers,
    )


def test_fixed_evaluation_set_has_exactly_30_cases_and_profile_boundaries() -> None:
    dataset = load_expert_template_evaluation_set(EXPERT_TEMPLATE_EVALUATION_PATH)

    assert len(dataset.cases) == 30
    assert len({case.id for case in dataset.cases}) == 30
    assert all(
        case.forbidden_layers == ("retail_sales_demo",)
        for case in dataset.cases
        if case.profile == "generic"
    )
    retail_workflow = next(case for case in dataset.cases if case.id == "r_workflow")
    assert retail_workflow.expected_template_ids == (
        "workflow.lakeflow_jobs",
        "retail.workflow_dag",
    )


@pytest.mark.asyncio
async def test_evaluator_calculates_recall_leaks_and_inheritance_misses() -> None:
    first_query = "命中核心模板"
    second_query = "发生 Profile 泄漏"
    third_query = "覆盖层缺少父模板"
    retriever = FakeRetriever(
        {
            first_query: _bundle(
                first_query,
                "generic",
                _selection(1, "workflow.lakeflow_jobs"),
            ),
            second_query: _bundle(
                second_query,
                "generic",
                _selection(
                    1,
                    "retail.project_context",
                    layer="retail_sales_demo",
                ),
            ),
            third_query: _bundle(
                third_query,
                "retail_sales_demo",
                _selection(
                    1,
                    "retail.workflow_dag",
                    layer="retail_sales_demo",
                    extends="workflow.lakeflow_jobs@1.0.0",
                ),
            ),
        }
    )
    embedding_client = FakeEmbeddingClient()
    dataset = ExpertTemplateEvaluationDataset(
        version=1,
        cases=(
            _case("hit", first_query, "workflow.lakeflow_jobs"),
            _case("leak", second_query, "workflow.lakeflow_jobs"),
            _case(
                "inheritance",
                third_query,
                "retail.workflow_dag",
                profile="retail_sales_demo",
                forbidden_layers=(),
            ),
        ),
    )

    result = await ExpertTemplateEvaluator(
        retriever=retriever,
        embedding_client=embedding_client,
    ).evaluate(dataset)

    assert result.query_count == 3
    assert result.hit_count == 2
    assert result.recall_at_3 == 0.6667
    assert result.profile_leak_count == 1
    assert result.inheritance_miss_count == 1
    assert result.passed is False
    assert len(result.failures) == 2
    assert embedding_client.queries == [first_query, second_query, third_query]


@pytest.mark.asyncio
async def test_evaluator_records_missing_context_as_miss() -> None:
    query = "没有上下文"
    evaluator = ExpertTemplateEvaluator(
        retriever=FakeRetriever({query: ExpertTemplateContextNotFoundError("没有专家模板上下文")}),
        embedding_client=FakeEmbeddingClient(),
    )

    result = await evaluator.evaluate(
        ExpertTemplateEvaluationDataset(
            version=1,
            cases=(_case("missing", query, "workflow.lakeflow_jobs"),),
        )
    )

    assert result.hit_count == 0
    assert result.recall_at_3 == 0.0
    assert result.results[0].actual_template_ids == ()


@pytest.mark.asyncio
async def test_cli_evaluate_uses_quality_exit_code_and_fixed_path(
    registry: ExpertTemplateRegistry,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = ExpertTemplateEvaluationResult(
        query_count=30,
        hit_count=29,
        recall_at_3=0.9667,
        profile_leak_count=0,
        inheritance_miss_count=0,
        passed=True,
        results=(),
        failures=(),
    )
    evaluator = FakeEvaluationRunner(result)
    runtime = ExpertTemplateCliRuntime(
        service=cast(ExpertTemplateSyncRunner, object()),
        repository=cast(ExpertTemplateStatusRepository, object()),
        registry=registry,
        evaluator=evaluator,
    )

    exit_code = await run_async(("evaluate",), runtime)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["recall_at_3"] == 0.9667
    assert evaluator.paths == [EXPERT_TEMPLATE_EVALUATION_PATH]


@pytest.mark.asyncio
async def test_cli_evaluate_returns_two_for_invalid_dataset(
    registry: ExpertTemplateRegistry,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evaluator = FakeEvaluationRunner(
        error=ExpertTemplateEvaluationError("C:/private/eval.yml invalid")
    )
    runtime = ExpertTemplateCliRuntime(
        service=cast(ExpertTemplateSyncRunner, object()),
        repository=cast(ExpertTemplateStatusRepository, object()),
        registry=registry,
        evaluator=evaluator,
    )

    exit_code = await run_async(("evaluate",), runtime)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "专家模板评估集无效" in captured.err
    assert "private" not in captured.err
