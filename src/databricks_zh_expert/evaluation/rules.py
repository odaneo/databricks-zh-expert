import io
import re
import tokenize
from urllib.parse import urlsplit

import sqlparse
from markdown_it import MarkdownIt

from databricks_zh_expert.evaluation.types import (
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationEvidence,
    EvaluationManualReviewResult,
    EvaluationRuleLevel,
    EvaluationRuleResult,
    ManualReviewStatus,
)

_FALSE_EXECUTION_PATTERNS = (
    re.compile(r"已经执行成功|已执行成功|已经部署完成|已部署完成|已上线成功|验证通过"),
    re.compile(r"\b(?:successfully\s+executed|successfully\s+deployed)\b", re.IGNORECASE),
)


def score_case(case: EvaluationCase, evidence: EvaluationEvidence) -> EvaluationCaseResult:
    hard: list[EvaluationRuleResult] = []
    expected = case.expected

    _hard(hard, "http_created", evidence.http_status == 201, "201", str(evidence.http_status))
    _hard(
        hard,
        "model_no_fallback",
        evidence.used_model == evidence.requested_model
        and not evidence.fallback_used
        and evidence.attempt_count == 1,
        f"仅使用 {evidence.requested_model.value}",
        (
            f"used={evidence.used_model.value if evidence.used_model else None}, "
            f"fallback={evidence.fallback_used}, attempts={evidence.attempt_count}"
        ),
    )
    _hard(
        hard,
        "prompt_contract",
        evidence.prompt_name is case.prompt,
        case.prompt.value,
        evidence.prompt_name.value if evidence.prompt_name else "null",
    )
    _hard(
        hard,
        "artifact_contract",
        evidence.artifact_type is expected.artifact_type,
        expected.artifact_type.value,
        evidence.artifact_type.value if evidence.artifact_type else "null",
    )
    _hard(
        hard,
        "project_fact_status",
        evidence.project_fact_status == expected.project_fact_status,
        str(expected.project_fact_status),
        str(evidence.project_fact_status),
    )
    _hard(
        hard,
        "model_call_success",
        evidence.model_call_success,
        "true",
        str(evidence.model_call_success),
    )
    _hard(
        hard,
        "artifact_valid",
        evidence.artifact_valid is True,
        "true",
        str(evidence.artifact_valid),
    )
    _hard(
        hard,
        "trace_complete",
        bool(evidence.model_call_ids) and evidence.model_call_ids == evidence.trace_model_call_ids,
        ",".join(str(item) for item in evidence.model_call_ids),
        ",".join(str(item) for item in evidence.trace_model_call_ids),
    )

    _score_citations(hard, case, evidence)
    _score_workspace(hard, case, evidence)
    _score_content(hard, case, evidence)

    false_claims = tuple(
        pattern.pattern
        for pattern in _FALSE_EXECUTION_PATTERNS
        if pattern.search(evidence.assistant_content)
    )
    _hard(
        hard,
        "no_false_execution_claim",
        not false_claims,
        "不得声称已经执行、部署或验证",
        ", ".join(false_claims) or "未发现",
    )

    soft = tuple(
        EvaluationRuleResult(
            rule_id=f"suggested_term_{index}",
            level=EvaluationRuleLevel.SOFT,
            passed=term.casefold() in evidence.assistant_content.casefold(),
            expected=term,
            actual="命中" if term.casefold() in evidence.assistant_content.casefold() else "未命中",
        )
        for index, term in enumerate(case.soft_checks.suggested_terms, start=1)
    )
    soft_score = round(sum(item.passed for item in soft) / len(soft), 4) if soft else 1.0
    hard_results = tuple(hard)
    hard_passed = all(item.passed for item in hard_results)
    manual_review = EvaluationManualReviewResult(
        required=case.manual_review.required,
        status=(
            ManualReviewStatus.PENDING
            if case.manual_review.required
            else ManualReviewStatus.NOT_REQUIRED
        ),
        questions=case.manual_review.questions,
    )
    return EvaluationCaseResult(
        case_id=case.id,
        title=case.title,
        group=case.group,
        prompt=case.prompt,
        model=evidence.requested_model,
        session_id=evidence.session_id,
        prompt_version=evidence.prompt_version,
        assistant_content=evidence.assistant_content,
        citation_urls=evidence.citation_urls,
        model_call_ids=evidence.model_call_ids,
        fallback_used=evidence.fallback_used,
        prompt_tokens=evidence.prompt_tokens,
        completion_tokens=evidence.completion_tokens,
        latency_ms=evidence.latency_ms,
        hard_rules=hard_results,
        soft_rules=soft,
        hard_passed=hard_passed,
        soft_score=soft_score,
        soft_minimum=case.soft_checks.minimum_score,
        automated_passed=hard_passed and soft_score >= case.soft_checks.minimum_score,
        manual_review=manual_review,
        error_code=evidence.error_code,
        error_message=evidence.error_message,
    )


def _score_citations(
    hard: list[EvaluationRuleResult],
    case: EvaluationCase,
    evidence: EvaluationEvidence,
) -> None:
    if not case.expected.require_official_citations:
        _hard(hard, "official_citations", True, "不要求", "不要求")
        _hard(hard, "official_citation_domain", True, "不要求", "不要求")
        return
    _hard(
        hard,
        "official_citations",
        bool(evidence.citation_urls),
        "至少 1 个结构化官方引用",
        str(len(evidence.citation_urls)),
    )
    invalid_urls = tuple(url for url in evidence.citation_urls if not _is_databricks_url(url))
    _hard(
        hard,
        "official_citation_domain",
        bool(evidence.citation_urls) and not invalid_urls,
        "databricks.com 官方域名",
        ", ".join(invalid_urls) or "全部有效",
    )


def _score_workspace(
    hard: list[EvaluationRuleResult],
    case: EvaluationCase,
    evidence: EvaluationEvidence,
) -> None:
    expected = case.expected
    if not expected.require_workspace_context:
        _hard(
            hard,
            "workspace_not_injected",
            not evidence.workspace_unit_ids and not evidence.workspace_source_paths,
            "无 Workspace Context",
            f"units={len(evidence.workspace_unit_ids)}",
        )
        return

    _hard(
        hard,
        "workspace_identity",
        evidence.workspace_id == "northwind_psql"
        and evidence.workspace_version is not None
        and bool(re.fullmatch(r"[0-9a-f]{64}", evidence.workspace_source_hash or "")),
        "northwind_psql + version + source hash",
        f"{evidence.workspace_id}/{evidence.workspace_version}/{evidence.workspace_source_hash}",
    )
    missing_units = tuple(
        unit_id
        for unit_id in expected.workspace_unit_ids
        if unit_id not in evidence.workspace_unit_ids
    )
    _hard(
        hard,
        "workspace_expected_units",
        not missing_units,
        ",".join(expected.workspace_unit_ids),
        "missing=" + ",".join(missing_units),
    )
    invalid_paths = tuple(
        path
        for path in evidence.workspace_source_paths
        if path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", path)
    )
    _hard(
        hard,
        "workspace_relative_paths",
        bool(evidence.workspace_source_paths) and not invalid_paths,
        "仅输入包相对路径",
        ",".join(invalid_paths) or "全部有效",
    )


def _score_content(
    hard: list[EvaluationRuleResult],
    case: EvaluationCase,
    evidence: EvaluationEvidence,
) -> None:
    expected = case.expected
    normalized = evidence.assistant_content.casefold()
    missing_terms = tuple(
        term for term in expected.required_terms if term.casefold() not in normalized
    )
    _hard(
        hard,
        "required_terms",
        not missing_terms,
        ",".join(expected.required_terms),
        "missing=" + ",".join(missing_terms),
    )

    missing_groups = tuple(
        "|".join(group)
        for group in expected.required_any_term_groups
        if not any(term.casefold() in normalized for term in group)
    )
    _hard(
        hard,
        "required_any_terms",
        not missing_groups,
        ";".join("|".join(group) for group in expected.required_any_term_groups) or "无",
        "missing=" + ";".join(missing_groups),
    )
    found_forbidden = tuple(
        term for term in expected.forbidden_terms if term.casefold() in normalized
    )
    _hard(
        hard,
        "forbidden_terms",
        not found_forbidden,
        "不得出现 " + ",".join(expected.forbidden_terms),
        ",".join(found_forbidden) or "未发现",
    )

    missing_patterns = tuple(
        pattern
        for pattern in expected.required_patterns
        if re.search(pattern, evidence.assistant_content) is None
    )
    _hard(
        hard,
        "required_patterns",
        not missing_patterns,
        ";".join(expected.required_patterns) or "无",
        "missing=" + ";".join(missing_patterns),
    )
    found_patterns = tuple(
        pattern
        for pattern in expected.forbidden_patterns
        if re.search(pattern, evidence.assistant_content)
    )
    _hard(
        hard,
        "forbidden_patterns",
        not found_patterns,
        "不得命中配置的禁止模式",
        ";".join(found_patterns) or "未发现",
    )

    missing_sections = tuple(
        section
        for section in expected.required_sections
        if re.search(rf"(?m)^##\s+{re.escape(section)}\s*$", evidence.assistant_content) is None
    )
    _hard(
        hard,
        "required_sections",
        not missing_sections,
        ",".join(expected.required_sections) or "无",
        "missing=" + ",".join(missing_sections),
    )

    code, language = _first_code_fence(evidence.assistant_content)
    _hard(
        hard,
        "code_fence_language",
        expected.code_fence_language is None or language == expected.code_fence_language,
        str(expected.code_fence_language),
        str(language),
    )
    normalized_code = _code_without_comments(code, language).casefold()
    missing_code_terms = tuple(
        term for term in expected.code_required_terms if term.casefold() not in normalized_code
    )
    _hard(
        hard,
        "code_required_terms",
        not missing_code_terms,
        ",".join(expected.code_required_terms) or "无",
        "missing=" + ",".join(missing_code_terms),
    )
    forbidden_code_terms = tuple(
        term for term in expected.code_forbidden_terms if term.casefold() in normalized_code
    )
    _hard(
        hard,
        "code_forbidden_terms",
        not forbidden_code_terms,
        "不得在代码中出现 " + ",".join(expected.code_forbidden_terms),
        ",".join(forbidden_code_terms) or "未发现",
    )


def _first_code_fence(content: str) -> tuple[str, str | None]:
    for token in MarkdownIt("commonmark").parse(content):
        if token.type != "fence":
            continue
        language = token.info.strip().split(maxsplit=1)[0].casefold() if token.info.strip() else ""
        return token.content, language
    return "", None


def _code_without_comments(code: str, language: str | None) -> str:
    if language == "sql":
        return sqlparse.format(code, strip_comments=True)
    if language != "python":
        return code
    try:
        tokens = tokenize.generate_tokens(io.StringIO(code).readline)
        return tokenize.untokenize(token for token in tokens if token.type != tokenize.COMMENT)
    except (IndentationError, tokenize.TokenError):
        return code


def _is_databricks_url(url: str) -> bool:
    hostname = (urlsplit(url).hostname or "").casefold()
    return hostname == "databricks.com" or hostname.endswith(".databricks.com")


def _hard(
    target: list[EvaluationRuleResult],
    rule_id: str,
    passed: bool,
    expected: str,
    actual: str,
) -> None:
    target.append(
        EvaluationRuleResult(
            rule_id=rule_id,
            level=EvaluationRuleLevel.HARD,
            passed=passed,
            expected=expected,
            actual=actual,
        )
    )
