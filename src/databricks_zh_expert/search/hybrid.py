import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

_LEXICAL_TOKEN_PATTERN = re.compile(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/-]+|[A-Za-z][A-Za-z0-9_.-]*")
_LEXICAL_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "databricks",
        "for",
        "how",
        "in",
        "is",
        "of",
        "on",
        "or",
        "please",
        "the",
        "to",
        "use",
        "what",
        "with",
    }
)


@dataclass(frozen=True, slots=True)
class FusionRank:
    item_id: UUID
    vector_rank: int | None
    lexical_rank: int | None
    fused_score: float


@dataclass(slots=True)
class _FusionState:
    item_id: UUID
    vector_rank: int | None = None
    lexical_rank: int | None = None


def extract_lexical_query(query: str) -> str:
    normalized = unicodedata.normalize("NFKC", query)
    terms: list[str] = []
    seen: set[str] = set()
    for match in _LEXICAL_TOKEN_PATTERN.finditer(normalized):
        term = match.group(0).rstrip(".-")
        normalized_term = term.casefold()
        if not term or normalized_term in _LEXICAL_STOP_WORDS or normalized_term in seen:
            continue
        if not term.startswith("/") and len(term) < 2:
            continue
        seen.add(normalized_term)
        terms.append(term)
    return " OR ".join(terms)


def reciprocal_rank_fusion_ids(
    vector_ids: Sequence[UUID],
    lexical_ids: Sequence[UUID],
    *,
    rrf_k: int = 60,
) -> tuple[FusionRank, ...]:
    if isinstance(rrf_k, bool) or not isinstance(rrf_k, int) or rrf_k <= 0:
        raise ValueError("RRF k 必须是正整数。")

    states: dict[UUID, _FusionState] = {}
    seen_vector: set[UUID] = set()
    for item_id in vector_ids:
        if item_id in seen_vector:
            continue
        seen_vector.add(item_id)
        state = states.setdefault(item_id, _FusionState(item_id=item_id))
        state.vector_rank = len(seen_vector)

    seen_lexical: set[UUID] = set()
    for item_id in lexical_ids:
        if item_id in seen_lexical:
            continue
        seen_lexical.add(item_id)
        state = states.setdefault(item_id, _FusionState(item_id=item_id))
        state.lexical_rank = len(seen_lexical)

    ranks = tuple(_to_rank(state, rrf_k=rrf_k) for state in states.values())
    return tuple(sorted(ranks, key=lambda rank: (-rank.fused_score, str(rank.item_id))))


def _to_rank(state: _FusionState, *, rrf_k: int) -> FusionRank:
    fused_score = 0.0
    if state.vector_rank is not None:
        fused_score += 1 / (rrf_k + state.vector_rank)
    if state.lexical_rank is not None:
        fused_score += 1 / (rrf_k + state.lexical_rank)
    return FusionRank(
        item_id=state.item_id,
        vector_rank=state.vector_rank,
        lexical_rank=state.lexical_rank,
        fused_score=fused_score,
    )
