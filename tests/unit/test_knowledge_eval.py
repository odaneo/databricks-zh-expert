import json
from io import BytesIO, TextIOWrapper
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

import databricks_zh_expert.rag.cli as cli_module
from databricks_zh_expert.rag.cli import (
    IndexStatusRepository,
    KnowledgeCliRuntime,
    run_async,
)
from databricks_zh_expert.rag.context import (
    KnowledgeContextNotFoundError,
    RankedKnowledgeChunk,
    RetrievalBundle,
)
from databricks_zh_expert.rag.evaluation import (
    REQUIRED_EVALUATION_CATEGORIES,
    EvaluationCaseResult,
    KnowledgeEvaluationCase,
    KnowledgeEvaluationDataset,
    KnowledgeEvaluationResult,
    KnowledgeEvaluator,
    RetrievedSource,
    load_evaluation_set,
)
from databricks_zh_expert.rag.ingestion import KnowledgeIngestionService


class FakeRetriever:
    def __init__(
        self,
        responses: dict[str, RetrievalBundle | Exception],
    ) -> None:
        self.responses = responses
        self.queries: list[str] = []

    async def retrieve(self, query: str) -> RetrievalBundle:
        self.queries.append(query)
        response = self.responses[query]
        if isinstance(response, Exception):
            raise response
        return response


class FakeEvaluationRunner:
    def __init__(self, result: KnowledgeEvaluationResult) -> None:
        self.result = result
        self.paths: list[Path] = []

    async def evaluate_file(self, path: Path) -> KnowledgeEvaluationResult:
        self.paths.append(path)
        return self.result


def _case(
    case_id: str,
    question: str,
    *expected_urls: str,
) -> KnowledgeEvaluationCase:
    return KnowledgeEvaluationCase(
        id=case_id,
        category="jobs",
        question=question,
        expected_urls=expected_urls,
    )


def _bundle(query: str, sources: tuple[tuple[str, str], ...]) -> RetrievalBundle:
    candidates = tuple(
        RankedKnowledgeChunk(
            chunk_id=UUID(int=index),
            chunk_hash=f"{index:064x}",
            document_id=UUID(int=100 + index),
            source_key=source_key,
            title=source_key,
            canonical_url=url,
            chunk_index=index,
            heading_path=(source_key,),
            content=f"Content for {source_key}",
            token_count=5,
            source_ref=f"https://docs.databricks.com/{source_key}/#section-{index}",
            vector_similarity=0.9 - (index / 100),
            lexical_score=None,
            vector_rank=index,
            lexical_rank=None,
            fused_score=1 / (60 + index),
        )
        for index, (source_key, url) in enumerate(sources, start=1)
    )
    return RetrievalBundle(
        query=query,
        ranked_candidates=candidates,
        selected_chunks=candidates[:6],
        citations=(),
        context="测试上下文",
        context_token_count=4,
    )


def _evaluation_result(*, passed: bool) -> KnowledgeEvaluationResult:
    case_result = EvaluationCaseResult(
        id="jobs-retry",
        category="jobs",
        question="Lakeflow Jobs 如何配置失败重试？",
        expected_urls=("https://docs.databricks.com/jobs/",),
        actual_sources=(
            RetrievedSource(
                source_key="docs-lakeflow-jobs",
                url="https://docs.databricks.com/jobs/",
            ),
        ),
        first_relevant_rank=1 if passed else None,
        hit=passed,
    )
    return KnowledgeEvaluationResult(
        case_count=1,
        top_k=5,
        minimum_recall=0.8,
        recall_at_5=1.0 if passed else 0.0,
        mrr=1.0 if passed else 0.0,
        passed=passed,
        results=(case_result,),
        failures=() if passed else (case_result,),
    )


def test_fixed_evaluation_set_has_required_coverage_and_official_urls() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    dataset = load_evaluation_set(repository_root / "tests/evals/databricks_rag.yml")

    assert len(dataset.cases) >= 20
    assert {case.category for case in dataset.cases} == REQUIRED_EVALUATION_CATEGORIES
    assert all(
        url.startswith(
            (
                "https://docs.databricks.com/",
                "https://www.databricks.com/",
            )
        )
        for case in dataset.cases
        for url in case.expected_urls
    )
    pricing_case = next(case for case in dataset.cases if case.id == "cost-pricing-link")
    assert pricing_case.expected_urls == ("https://www.databricks.com/product/pricing",)


@pytest.mark.asyncio
async def test_evaluator_calculates_source_level_recall_and_mrr() -> None:
    first_question = "如何配置任务失败重试？"
    second_question = "如何查看 Unity Catalog 血缘？"
    retriever = FakeRetriever(
        {
            first_question: _bundle(
                first_question,
                (
                    (
                        "databricks-docs-tasks",
                        "https://docs.databricks.com/aws/en/jobs/configure-task",
                    ),
                    (
                        "databricks-docs-tasks",
                        "https://docs.databricks.com/aws/en/jobs/configure-task",
                    ),
                    (
                        "databricks-docs-jobs",
                        "https://docs.databricks.com/aws/en/jobs/",
                    ),
                    (
                        "databricks-docs-scheduling",
                        "https://docs.databricks.com/aws/en/jobs/scheduled",
                    ),
                ),
            ),
            second_question: _bundle(
                second_question,
                (
                    (
                        "databricks-docs-unity-catalog",
                        "https://docs.databricks.com/aws/en/data-governance/unity-catalog/",
                    ),
                    (
                        "databricks-docs-unity-access",
                        "https://docs.databricks.com/aws/en/data-governance/unity-catalog/access-control",
                    ),
                ),
            ),
        }
    )
    dataset = KnowledgeEvaluationDataset(
        version=1,
        cases=(
            _case("jobs-retry", first_question, "https://docs.databricks.com/jobs/"),
            _case(
                "unity-lineage",
                second_question,
                "https://docs.databricks.com/data-governance/unity-catalog/data-lineage",
            ),
        ),
    )

    result = await KnowledgeEvaluator(retriever).evaluate(dataset)

    assert result.case_count == 2
    assert result.recall_at_5 == 0.5
    assert result.mrr == 0.25
    assert result.passed is False
    assert result.results[0].first_relevant_rank == 2
    assert result.results[0].actual_sources == (
        RetrievedSource(
            source_key="databricks-docs-tasks",
            url="https://docs.databricks.com/aws/en/jobs/configure-task",
        ),
        RetrievedSource(
            source_key="databricks-docs-jobs",
            url="https://docs.databricks.com/aws/en/jobs/",
        ),
        RetrievedSource(
            source_key="databricks-docs-scheduling",
            url="https://docs.databricks.com/aws/en/jobs/scheduled",
        ),
    )
    assert result.failures == (result.results[1],)
    assert retriever.queries == [first_question, second_question]


@pytest.mark.asyncio
async def test_evaluator_records_missing_context_as_failed_case() -> None:
    question = "不在知识库中的问题"
    retriever = FakeRetriever({question: KnowledgeContextNotFoundError("没有相关上下文")})
    dataset = KnowledgeEvaluationDataset(
        version=1,
        cases=(
            _case(
                "missing-context",
                question,
                "https://docs.databricks.com/jobs/",
            ),
        ),
    )

    result = await KnowledgeEvaluator(retriever).evaluate(dataset)

    assert result.recall_at_5 == 0.0
    assert result.mrr == 0.0
    assert result.results[0].actual_sources == ()
    assert result.results[0].first_relevant_rank is None
    assert result.failures == result.results


@pytest.mark.parametrize(
    ("passed", "expected_exit_code"),
    ((True, 0), (False, 1)),
)
@pytest.mark.asyncio
async def test_cli_evaluate_prints_result_and_uses_quality_exit_code(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    passed: bool,
    expected_exit_code: int,
) -> None:
    evaluation_path = tmp_path / "databricks_rag.yml"
    evaluator = FakeEvaluationRunner(_evaluation_result(passed=passed))
    runtime = KnowledgeCliRuntime(
        service=cast(KnowledgeIngestionService, object()),
        repository=cast(IndexStatusRepository, object()),
        evaluator=evaluator,
        evaluation_path=evaluation_path,
    )

    exit_code = await run_async(("evaluate",), runtime)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == expected_exit_code
    assert payload["passed"] is passed
    assert payload["recall_at_5"] == (1.0 if passed else 0.0)
    assert payload["results"][0]["actual_sources"][0]["source_key"] == ("docs-lakeflow-jobs")
    assert evaluator.paths == [evaluation_path]


def test_cli_configures_standard_streams_for_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = TextIOWrapper(BytesIO(), encoding="ascii")
    stderr = TextIOWrapper(BytesIO(), encoding="ascii")
    monkeypatch.setattr(cli_module.sys, "stdout", stdout)
    monkeypatch.setattr(cli_module.sys, "stderr", stderr)

    cli_module._configure_utf8_stdio()

    assert stdout.encoding == "utf-8"
    assert stderr.encoding == "utf-8"
