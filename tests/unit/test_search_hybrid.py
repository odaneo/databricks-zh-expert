from uuid import UUID

import pytest

from databricks_zh_expert.search.hybrid import (
    extract_lexical_query,
    reciprocal_rank_fusion_ids,
)


def test_rrf_ids_returns_stable_ranks() -> None:
    result = reciprocal_rank_fusion_ids(
        vector_ids=(UUID(int=1), UUID(int=2)),
        lexical_ids=(UUID(int=2), UUID(int=3)),
        rrf_k=60,
    )

    assert [item.item_id for item in result] == [UUID(int=2), UUID(int=1), UUID(int=3)]
    assert result[0].vector_rank == 2
    assert result[0].lexical_rank == 1
    assert result[0].fused_score == pytest.approx((1 / 62) + (1 / 61))


def test_rrf_ids_deduplicates_each_channel_and_uses_uuid_tie_breaker() -> None:
    result = reciprocal_rank_fusion_ids(
        vector_ids=(UUID(int=2), UUID(int=2), UUID(int=3)),
        lexical_ids=(UUID(int=1),),
    )

    assert [item.item_id for item in result] == [UUID(int=1), UUID(int=2), UUID(int=3)]
    assert result[1].vector_rank == 1
    assert result[2].vector_rank == 2


@pytest.mark.parametrize("rrf_k", [0, -1, True, 1.5])
def test_rrf_ids_rejects_invalid_k(rrf_k: object) -> None:
    with pytest.raises(ValueError, match="RRF k 必须是正整数"):
        reciprocal_rank_fusion_ids((), (), rrf_k=rrf_k)  # type: ignore[arg-type]


def test_shared_lexical_query_keeps_precise_terms_and_paths() -> None:
    assert (
        extract_lexical_query("如何用 OPTIMIZE 配合 run_if，并调用 /api/2.1/jobs/runs/submit？")
        == "OPTIMIZE OR run_if OR /api/2.1/jobs/runs/submit"
    )
