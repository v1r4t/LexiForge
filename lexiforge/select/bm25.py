from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Iterable, List, Mapping, Sequence

from lexiforge.canon import tokens as canon_tokens


class BM25Index:
    def __init__(self, glossary: Mapping[str, Any] | Sequence[Mapping[str, Any]]):
        if isinstance(glossary, Mapping):
            items = list(glossary.values())
        else:
            items = list(glossary)

        self.k1 = 1.2
        self.b = 0.75

        self.docs: List[List[str]] = []
        self.doc_ids: List[str] = []
        self.doc_term_ids: List[List[str]] = []
        self.term_id_to_doc_ids: dict[str, set[int]] = defaultdict(set)
        self.avgdl = 0.0
        self.idf: dict[str, float] = {}
        self.N = 0

        for item in items:
            term_id = self._get_term_id(item)
            if not term_id:
                continue
            doc_terms = self._build_document_tokens(item)
            if not doc_terms:
                continue
            self.docs.append(doc_terms)
            self.doc_ids.append(str(term_id))
            self.doc_term_ids.append(doc_terms)
            self.N += 1

        self._compute_stats()

    def _get_term_id(self, item: Mapping[str, Any]) -> str | None:
        for key in ("id", "term_id", "termId", "canonical_id", "key"):
            if key in item and item[key] is not None:
                return str(item[key])
        canonical = item.get("canonical") or item.get("term") or item.get("name")
        if canonical is not None:
            return str(canonical)
        return None

    def _build_document_tokens(self, item: Mapping[str, Any]) -> List[str]:
        tokens_out: List[str] = []
        seen_local = set()

        def add_text(text: Any):
            if not text:
                return
            tks = canon_tokens(str(text))
            for tk in tks:
                if not tk:
                    continue
                if tk in seen_local:
                    continue
                seen_local.add(tk)
                tokens_out.append(tk)

        add_text(item.get("canonical"))
        add_text(item.get("term"))
        add_text(item.get("name"))

        aliases = item.get("aliases") or item.get("alias") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        for a in aliases:
            add_text(a)

        categories = item.get("categories") or item.get("category") or []
        if isinstance(categories, str):
            categories = [categories]
        for c in categories:
            add_text(c)

        return tokens_out

    def _compute_stats(self):
        if self.N == 0:
            self.avgdl = 0.0
            self.idf = {}
            return
        total_dl = sum(len(d) for d in self.docs)
        self.avgdl = total_dl / self.N if self.N > 0 else 0.0
        df: dict[str, int] = defaultdict(int)
        for doc_idx, doc_terms in enumerate(self.docs):
            # df counts terms that appear in document
            for t in set(doc_terms):
                df[t] += 1
                self.term_id_to_doc_ids[t].add(doc_idx)
        for t, dft in df.items():
            # BM25 IDF
            self.idf[t] = math.log((self.N - dft + 0.5) / (dft + 0.5) + 1.0)

    def get_scores(self, query_terms: Sequence[str]) -> List[tuple[str, float]]:
        if self.N == 0 or not query_terms:
            return []
        qterms = []
        for qt in query_terms:
            qterms.extend(canon_tokens(str(qt)))
        if not qterms:
            return []
        scores = [0.0] * self.N
        # term frequencies per doc
        for doc_idx, doc_terms in enumerate(self.docs):
            if not doc_terms:
                continue
            tf = Counter(doc_terms)
            dl = len(doc_terms)
            for qt in qterms:
                if qt not in tf:
                    continue
                f = tf[qt]
                idf_t = self.idf.get(qt, math.log((self.N + 0.5) / (0.5 + 1.0)))
                denom = f + self.k1 * (1.0 - self.b + self.b * dl / self.avgdl if self.avgdl > 0 else 1.0)
                score = idf_t * ((f * (self.k1 + 1.0)) / denom) if denom > 0 else 0.0
                scores[doc_idx] += score
        results = []
        for doc_idx, s in enumerate(scores):
            if s > 0.0:
                results.append((self.doc_ids[doc_idx], s))
        # deterministic tie-break: if scores equal, by term id string
        results.sort(key=lambda x: (-x[1], x[0]))
        return results

    def select(self, hypothesis: str | Sequence[str], budget: int = 200) -> List[str]:
        if isinstance(hypothesis, str):
            query_terms = canon_tokens(hypothesis)
        else:
            # concatenate hypotheses
            all_terms = []
            for h in hypothesis:
                all_terms.extend(canon_tokens(str(h)))
            query_terms = all_terms
        scores = self.get_scores(query_terms)
        selected = []
        seen = set()
        for term_id, _score in scores:
            if term_id in seen:
                continue
            selected.append(term_id)
            seen.add(term_id)
            if len(selected) >= budget:
                break
        return selected


def selector_recall_decomposition(
    pass1_errors: Iterable[Mapping[str, Any]] | Mapping[str, Any],
    selected: Sequence[str],
    glossary_ids: Iterable[str],
    candidate_ids: Iterable[str],
) -> dict:
    if isinstance(pass1_errors, Mapping) and "errors" in pass1_errors:
        errors_list = list(pass1_errors["errors"])  # type: ignore
    elif isinstance(pass1_errors, Mapping):
        # maybe mapping of id->info
        errors_list = list(pass1_errors.values())  # type: ignore
    else:
        errors_list = list(pass1_errors)

    glossary_set = set(str(g) for g in glossary_ids)
    candidate_set = set(str(c) for c in candidate_ids)
    selected_set = set(str(s) for s in selected)
    selected_list = list(str(s) for s in selected)

    # identify errors by term id
    error_term_ids = []
    for e in errors_list:
        if isinstance(e, str):
            error_term_ids.append(e)
            continue
        if isinstance(e, Mapping):
            for k in ("term_id", "id", "termId", "canonical_id", "term", "canonical"):
                if k in e and e[k] is not None:
                    error_term_ids.append(str(e[k]))
                    break
            else:
                continue
        else:
            continue

    # coverage: errors absent from glossary at all
    errors_absent_from_glossary = []
    for tid in error_term_ids:
        if tid not in glossary_set:
            errors_absent_from_glossary.append(tid)
    coverage = len(errors_absent_from_glossary) / len(error_term_ids) if error_term_ids else 0.0

    # retrieval: of the rest (errors that are in glossary), share entering the candidate set
    errors_in_glossary = [tid for tid in error_term_ids if tid in glossary_set]
    if errors_in_glossary:
        errors_in_glossary_in_candidates = [tid for tid in errors_in_glossary if tid in candidate_set]
        retrieval = len(errors_in_glossary_in_candidates) / len(errors_in_glossary)
    else:
        retrieval = 0.0

    # ranking: of those (errors in glossary that entered candidate set), share inside top 200
    errors_in_candidates = [tid for tid in error_term_ids if tid in glossary_set and tid in candidate_set]
    if errors_in_candidates:
        errors_in_candidates_in_top200 = [tid for tid in errors_in_candidates if tid in selected_set]
        # also could be position-based, but "share inside top 200" - presence in selected up to budget
        ranking = len(errors_in_candidates_in_top200) / len(errors_in_candidates)
    else:
        ranking = 0.0

    return {
        "coverage": coverage,
        "retrieval": retrieval,
        "ranking": ranking,
    }
