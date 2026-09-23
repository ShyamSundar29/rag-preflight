"""Embedding-input cost estimates using explicitly supplied token evidence."""
from collections.abc import Callable, Mapping, Iterable
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from typing import Any
from .reingestion import UpdatePlan


@dataclass(frozen=True)
class EmbeddingCostEstimate:
    tokens_to_embed: int
    comparison_tokens: int | None
    estimated_cost: Decimal
    avoided_cost: Decimal | None
    price_per_million_tokens: Decimal
    currency: str
    comparison_scope: str | None

    def to_dict(self) -> dict[str, Any]:
        return dict(estimate=True, tokens_to_embed=self.tokens_to_embed,
                    comparison_tokens=self.comparison_tokens, estimated_cost=str(self.estimated_cost),
                    avoided_embedding_cost=None if self.avoided_cost is None else str(self.avoided_cost),
                    price_per_million_tokens=str(self.price_per_million_tokens), currency=self.currency,
                    comparison_scope=self.comparison_scope,
                    excluded_costs=['database', 'generation', 'network', 'retries'])


def estimate_embedding_cost(plan: UpdatePlan, *, price_per_million_tokens: Any, currency: str,
                            token_counts: Mapping[str, int] | None = None,
                            embedding_inputs: Mapping[str, str] | None = None,
                            tokenizer: Callable[[str], int] | None = None,
                            comparison_ids: Iterable[str] | None = None,
                            comparison_scope: str | None = None) -> EmbeddingCostEstimate:
    """Counts/inputs must cover exact preprocessed inputs, including prefixes.

    comparison_ids defines an explicit candidate-batch re-embedding comparison;
    hash-only snapshots do not contain text or token counts. No counts are guessed.
    """
    if not isinstance(plan, UpdatePlan):
        raise TypeError('Supply an UpdatePlan')
    try:
        if isinstance(price_per_million_tokens, bool):
            raise ValueError('Invalid price')
        price = Decimal(str(price_per_million_tokens))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('Price must be finite and nonnegative') from exc
    if not price.is_finite() or price < 0:
        raise ValueError('Price must be finite and nonnegative')
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError('Supply currency')
    if (embedding_inputs is None) != (tokenizer is None):
        raise ValueError('Supply both embedding_inputs and tokenizer')
    if token_counts is not None and embedding_inputs is not None:
        raise ValueError('Supply counts or tokenizer inputs, not both')
    counts = dict(token_counts or {})
    for key, count in counts.items():
        if not isinstance(key, str) or type(count) is not int or count < 0:
            raise ValueError('Token counts must be nonnegative Python integers keyed by chunk ID')
    if comparison_ids is None:
        if comparison_scope is not None:
            raise ValueError('comparison_scope requires comparison_ids')
        comparison = None
    else:
        if isinstance(comparison_ids, (str, bytes)) or not isinstance(comparison_scope, str) or not comparison_scope.strip():
            raise ValueError('Supply comparison IDs and explicit savings scope')
        comparison = tuple(comparison_ids)
        target_ids = {c.chunk_id for c in plan.target.chunks}
        if any(not isinstance(i, str) or i not in target_ids for i in comparison) or len(set(comparison)) != len(comparison):
            raise ValueError('Comparison requires unique target IDs')
        if not set(plan.embed_ids) <= set(comparison):
            raise ValueError('Comparison must include all planned embeddings')
    needed = set(plan.embed_ids) | set(comparison or ())
    if embedding_inputs is not None:
        assert tokenizer is not None
        for key in sorted(needed):
            if key not in embedding_inputs or not isinstance(embedding_inputs[key], str):
                raise ValueError(f'Missing embedding input for {key}')
            count = tokenizer(embedding_inputs[key])
            if type(count) is not int or count < 0:
                raise ValueError('Tokenizer must return a nonnegative Python integer')
            counts[key] = count
    if needed - counts.keys():
        raise ValueError('Missing actual embedding-input token counts; snapshots are hash-only')
    tokens = sum(counts[i] for i in plan.embed_ids)
    baseline = None if comparison is None else sum(counts[i] for i in comparison)
    cost = price * tokens / Decimal(1_000_000)
    avoided = None if baseline is None else price * (baseline - tokens) / Decimal(1_000_000)
    return EmbeddingCostEstimate(tokens, baseline, cost, avoided, price, currency, comparison_scope)
