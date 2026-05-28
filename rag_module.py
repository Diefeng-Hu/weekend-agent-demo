"""Local RAG module for Beijing weekend route recommendations.

The module works out of the box without external API keys by using a lightweight
TF-IDF retriever. If LangChain + Chroma + OpenAI embeddings are installed and an
OPENAI_API_KEY is available, it can also build a vector store for semantic search.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TOP_K = 3
DEFAULT_DATA_PATH = Path(__file__).with_name("beijing_routes.json")
DEFAULT_PERSIST_DIR = Path(__file__).with_name("chroma_beijing_routes")


@dataclass(frozen=True)
class RouteDocument:
    """A searchable route record."""

    id: str
    title: str
    content: str
    metadata: dict[str, object]


def load_routes(data_path: str | Path = DEFAULT_DATA_PATH) -> list[dict[str, object]]:
    """Load Beijing route data from JSON."""

    path = Path(data_path)
    if not path.exists():
        raise FileNotFoundError(f"Route data file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        routes: list[dict[str, object]] = json.load(file)  # type: ignore[arg-type,no-any-return]
    return routes


def save_routes(routes: Sequence[dict[str, object]], data_path: str | Path = DEFAULT_DATA_PATH) -> None:
    """Persist route data to JSON."""

    path = Path(data_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(list(routes), file, ensure_ascii=False, indent=2)
        _ = file.write("\n")


def add_route(route: dict[str, object], data_path: str | Path = DEFAULT_DATA_PATH) -> None:
    """Incrementally add or replace one route by id."""

    required_fields = {"id", "title", "spots", "route", "duration"}
    missing = required_fields - set(route)
    if missing:
        raise ValueError(f"Missing required route fields: {', '.join(sorted(missing))}")

    routes = load_routes(data_path)
    routes = [item for item in routes if item.get("id") != route["id"]]
    routes.append(route)
    save_routes(routes, data_path)


def route_to_document(route: dict[str, object]) -> RouteDocument:
    """Convert a route JSON object into searchable text."""

    spots_val: object = route.get("spots", [])  # type: ignore[assignment]
    if isinstance(spots_val, list):
        spots = "、".join(str(s) for s in spots_val if isinstance(s, str))  # type: ignore[misc,unknown-member]
    else:
        spots = ""
    suitable_for_val: object = route.get("suitable_for", [])  # type: ignore[assignment]
    if isinstance(suitable_for_val, list):
        suitable_for = "、".join(str(s) for s in suitable_for_val if isinstance(s, str))  # type: ignore[misc,unknown-member]
    else:
        suitable_for = ""
    highlights_val: object = route.get("highlights", [])  # type: ignore[assignment]
    if isinstance(highlights_val, list):
        highlights = "、".join(str(h) for h in highlights_val if isinstance(h, str))  # type: ignore[misc,unknown-member]
    else:
        highlights = ""
    content = "\n".join(
        [
            f"标题：{route.get('title', '')}",
            f"适合：{suitable_for}",
            f"时长：{route.get('duration', '')}",
            f"景点：{spots}",
            f"路线：{route.get('route', '')}",
            f"亮点：{highlights}",
            f"提示：{route.get('tips', '')}",
        ]
    )
    return RouteDocument(
        id=str(route.get("id", route.get("title", ""))),  # type: ignore[arg-type]
        title=str(route.get("title", "")),  # type: ignore[arg-type]
        content=content,
        metadata=route,  # type: ignore[arg-type]
    )


def tokenize(text: str) -> list[str]:
    """Tokenize mixed Chinese/English text for local retrieval."""

    normalized = text.lower()
    latin_tokens = re.findall(r"[a-z0-9]+", normalized)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
    chinese_bigrams = ["".join(chinese_chars[i : i + 2]) for i in range(max(0, len(chinese_chars) - 1))]
    return latin_tokens + chinese_chars + chinese_bigrams


class LocalTfidfRetriever:
    """Small dependency-free TF-IDF retriever for local demos and fallback use."""

    documents: list[RouteDocument]
    doc_tokens: list[list[str]]
    doc_tf: list[Counter[str]]
    idf: dict[str, float]
    doc_vectors: list[dict[str, float]]
    doc_norms: list[float]

    def __init__(self, documents: Sequence[RouteDocument]) -> None:
        self.documents = list(documents)
        self.doc_tokens = [tokenize(doc.content) for doc in self.documents]
        self.doc_tf = [Counter(tokens) for tokens in self.doc_tokens]
        self.idf = self._build_idf(self.doc_tokens)
        self.doc_vectors = [self._vectorize_counter(counter) for counter in self.doc_tf]
        self.doc_norms = [self._norm(vector) for vector in self.doc_vectors]

    @staticmethod
    def _build_idf(doc_tokens: Sequence[Sequence[str]]) -> dict[str, float]:
        doc_count = len(doc_tokens)
        df: Counter[str] = Counter()
        for tokens in doc_tokens:
            df.update(set(tokens))
        return {token: math.log((doc_count + 1) / (freq + 1)) + 1 for token, freq in df.items()}

    def _vectorize_counter(self, counter: Counter[str]) -> dict[str, float]:
        total = sum(counter.values()) or 1
        return {token: (freq / total) * self.idf.get(token, 0.0) for token, freq in counter.items()}

    @staticmethod
    def _norm(vector: dict[str, float]) -> float:
        return math.sqrt(sum(value * value for value in vector.values())) or 1.0

    def _query_vector(self, query: str) -> tuple[dict[str, float], float]:
        counter = Counter(tokenize(query))
        vector = self._vectorize_counter(counter)
        return vector, self._norm(vector)

    @staticmethod
    def _cosine(left: dict[str, float], right: dict[str, float], left_norm: float, right_norm: float) -> float:
        if len(left) > len(right):
            left, right = right, left
        dot = sum(value * right.get(token, 0.0) for token, value in left.items())
        return dot / (left_norm * right_norm)

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[tuple[RouteDocument, float]]:
        query_vector, query_norm = self._query_vector(query)
        scored = [
            (doc, self._cosine(query_vector, vector, query_norm, norm))
            for doc, vector, norm in zip(self.documents, self.doc_vectors, self.doc_norms)
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]


class BeijingRouteRAG:
    """RAG facade that retrieves routes and generates recommendation reasons."""

    data_path: Path
    routes: list[dict[str, object]]
    documents: list[RouteDocument]
    use_langchain: bool
    vector_store: object | None
    local_retriever: LocalTfidfRetriever

    def __init__(self, data_path: str | Path = DEFAULT_DATA_PATH, use_langchain: bool = False) -> None:
        self.data_path = Path(data_path)
        self.routes = load_routes(self.data_path)
        self.documents = [route_to_document(route) for route in self.routes]
        self.use_langchain = use_langchain
        self.vector_store = self._try_build_langchain_store() if use_langchain else None
        self.local_retriever = LocalTfidfRetriever(self.documents)

    def _try_build_langchain_store(self) -> object | None:
        """Build a Chroma vector store when optional dependencies are available."""

        try:
            from langchain_chroma import Chroma  # type: ignore[import-untyped,import-unresolved]
            from langchain_core.documents import Document  # type: ignore[import-untyped,import-unresolved]
            from langchain_openai import OpenAIEmbeddings  # type: ignore[import-untyped,import-unresolved]
        except Exception:
            return None

        if not os.getenv("OPENAI_API_KEY"):
            return None

        docs: list[object] = [
            Document(page_content=doc.content, metadata={"id": doc.id, "title": doc.title})  # type: ignore[call-arg,unknown-argument,unknown-member]
            for doc in self.documents
        ]
        embeddings: object = OpenAIEmbeddings()  # type: ignore[no-redef,unknown-member]
        vector_store: object = Chroma.from_documents(docs, embeddings, persist_directory=str(DEFAULT_PERSIST_DIR))  # type: ignore[no-redef,unknown-member,call-arg]
        return vector_store  # type: ignore[return-value]

    def retrieve(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[tuple[RouteDocument, float]]:
        """Retrieve Top-K route documents."""

        if self.vector_store is not None:
            from langchain.vectorstores import VectorStore  # type: ignore[import-untyped,import-unresolved,unused-import]

            vs = self.vector_store  # type: ignore[no-redef]
            results = vs.similarity_search_with_relevance_scores(query, k=top_k)  # type: ignore[union-attr,unknown-member]
            by_id = {doc.id: doc for doc in self.documents}
            converted: list[tuple[RouteDocument, float]] = []
            for lc_doc, score in results:  # type: ignore[misc,unknown-member]
                route_id: object = lc_doc.metadata.get("id")  # type: ignore[union-attr,unknown-member]
                if route_id in by_id:
                    converted.append((by_id[str(route_id)], float(score)))  # type: ignore[arg-type,unknown-argument]
            if converted:
                return dedupe_results(converted, top_k)
        return dedupe_results(self.local_retriever.search(query, top_k=top_k * 2), top_k)

    def recommend(self, query: str, top_k: int = DEFAULT_TOP_K) -> dict[str, object]:
        """Return personalized Beijing weekend route recommendations."""

        matches = self.retrieve(query, top_k=max(top_k * 3, len(self.documents)))
        matches = rerank_by_route_intent(query, matches)[:top_k]
        recommendations: list[dict[str, object]] = []
        for rank, (doc, score) in enumerate(matches, start=1):
            route: dict[str, object] = doc.metadata
            recommendations.append(
                {  # type: ignore[dict-item]
                    "rank": rank,
                    "score": round(float(score), 4),
                    "id": route.get("id"),
                    "title": route.get("title"),
                    "duration": route.get("duration"),
                    "estimated_cost_per_person": route.get("estimated_cost_per_person"),
                    "spots": route.get("spots", []),
                    "route": route.get("route"),
                    "reason": generate_reason(query, route),
                    "tips": route.get("tips"),
                }
            )
        return {"query": query, "top_k": top_k, "recommendations": recommendations}  # type: ignore[return-value]


def rerank_by_route_intent(
    query: str, results: list[tuple[RouteDocument, float]]
) -> list[tuple[RouteDocument, float]]:
    """Boost results whose route metadata matches query intent keywords."""
    keywords = tokenize(query)
    scored: list[tuple[RouteDocument, float]] = []
    for doc, base_score in results:
        metadata: dict[str, object] = doc.metadata
        boost = 0.0
        for key in ("suitable_for", "highlights", "route", "title", "spots"):
            value: object = metadata.get(key, "")  # type: ignore[assignment]
            if isinstance(value, list):
                value = " ".join(str(v) for v in value)  # type: ignore[misc,unknown-member]
            if isinstance(value, str):
                value_lower = value.lower()
                hits = sum(1 for kw in keywords if kw in value_lower)
                boost += hits * 0.05
        scored.append((doc, base_score + boost))
    scored.sort(key=lambda item: item[1], reverse=True)  # type: ignore[arg-type]
    return scored


def dedupe_results(results: Iterable[tuple[RouteDocument, float]], top_k: int) -> list[tuple[RouteDocument, float]]:
    """Remove duplicate or near-empty routes."""

    seen_titles: set[str] = set()
    deduped: list[tuple[RouteDocument, float]] = []
    for doc, score in results:
        normalized_title = re.sub(r"\s+", "", doc.title)
        if not normalized_title or normalized_title in seen_titles:
            continue
        seen_titles.add(normalized_title)
        deduped.append((doc, score))
        if len(deduped) >= top_k:
            break
    return deduped


def generate_reason(query: str, route: dict[str, object]) -> str:
    """Generate a concise natural-language recommendation reason."""

    _query_text = query.lower()
    route_suitable_for: object = route.get("suitable_for", [])  # type: ignore[assignment]
    if isinstance(route_suitable_for, list):
        suitable_for: set[str] = set(str(s) for s in route_suitable_for if isinstance(s, str))  # type: ignore[misc,unknown-member]
    else:
        suitable_for = set()
    route_highlights: object = route.get("highlights", [])  # type: ignore[assignment]
    if isinstance(route_highlights, list):
        highlights_list: list[str] = [str(h) for h in route_highlights if isinstance(h, str)]  # type: ignore[misc,unknown-member]
    else:
        highlights_list = []
    route_spots: object = route.get("spots", [])  # type: ignore[assignment]
    if isinstance(route_spots, list):
        spots_list: list[str] = [str(sp) for sp in route_spots if isinstance(sp, str)]  # type: ignore[misc,unknown-member]
    else:
        spots_list = []
    spots = "、".join(spots_list[:3])

    matched_tags: list[str] = [tag for tag in suitable_for if tag and tag in query]
    if "家庭" in query or "亲子" in query or "孩子" in query:
        matched_tags.append("亲子友好")
    if "情侣" in query or "约会" in query:
        matched_tags.append("适合约会")
    if "雨" in query or "室内" in query:
        matched_tags.append("天气风险低")
    if "一个人" in query or "独处" in query:
        matched_tags.append("适合独处放松")

    tag_text = "、".join(dict.fromkeys(matched_tags[:3])) or "与你的需求匹配"
    highlight_text = "、".join(highlights_list[:2]) if highlights_list else "路线完整"
    return f"这条路线{tag_text}，覆盖{spots}，{highlight_text}，整体时长约{route.get('duration', '半天到一天')}。"


def format_recommendations(result: dict[str, object]) -> str:
    """Format recommendations as a readable dialogue response."""

    lines: list[str] = [f"根据“{result['query']}”，推荐以下北京周末路线："]
    recs: object = result.get("recommendations", [])  # type: ignore[assignment]
    recommendations: list[dict[str, object]] = (
        list(recs) if isinstance(recs, list) else []  # type: ignore[misc,unknown-argument]
    )
    for item in recommendations:
        item_spots: object = item.get("spots", [])  # type: ignore[assignment]
        if isinstance(item_spots, list):
            spots = "、".join(str(s) for s in item_spots if isinstance(s, str))  # type: ignore[misc,unknown-member]
        else:
            spots = ""
        cost: object | None = item.get("estimated_cost_per_person")  # type: ignore[assignment]
        cost_text: str = f"人均约¥{cost}" if cost is not None else "费用视实际消费而定"
        item_rank: object = item["rank"]  # type: ignore[index]
        item_title: object = item["title"]  # type: ignore[index]
        item_duration: object = item["duration"]  # type: ignore[index]
        item_route: object = item["route"]  # type: ignore[index]
        item_reason: object = item["reason"]  # type: ignore[index]
        lines.extend(
            [
                f"\n{item_rank}. {item_title}",
                f"   - 时长：{item_duration}，{cost_text}",
                f"   - 景点：{spots}",
                f"   - 路线：{item_route}",
                f"   - 推荐理由：{item_reason}",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Beijing weekend route RAG demo")
    _ = parser.add_argument("query", nargs="?", default="适合家庭的周末游", help="User query")
    _ = parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Number of recommendations")
    _ = parser.add_argument("--data", default=str(DEFAULT_DATA_PATH), help="Route JSON path")
    _ = parser.add_argument("--langchain", action="store_true", help="Use LangChain + Chroma when available")
    _ = parser.add_argument("--json", action="store_true", help="Print raw JSON")
    args: argparse.Namespace = parser.parse_args()

    rag = BeijingRouteRAG(data_path=str(args.data), use_langchain=bool(args.langchain))  # type: ignore[arg-type,no-any-argument]
    query_arg: str = str(args.query)  # type: ignore[arg-type,no-any-argument]
    top_k_arg: int = int(args.top_k)  # type: ignore[arg-type,no-any-argument]
    result: dict[str, object] = rag.recommend(query_arg, top_k=top_k_arg)
    json_arg: bool = bool(args.json)  # type: ignore[arg-type,no-any-argument]
    if json_arg:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_recommendations(result))


if __name__ == "__main__":
    main()