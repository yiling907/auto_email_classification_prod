"""
RAG Retrieval Lambda Function
Hybrid retrieval: HyDE query expansion → vector + BM25 → RRF fusion → cross-encoder rerank
"""
import json
import math
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Tuple

import boto3
from botocore.exceptions import ClientError

# Shared ReAct / CoT utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../shared'))
from reasoning_utils import extract_react_answer

# ── AWS clients ───────────────────────────────────────────────────────────────
bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb        = boto3.resource('dynamodb')

# ── Config ────────────────────────────────────────────────────────────────────
EMBEDDINGS_TABLE_NAME    = os.environ['EMBEDDINGS_TABLE_NAME']
TITAN_EMBEDDINGS_MODEL_ID = "amazon.titan-embed-text-v2:0"
MISTRAL_MODEL_ID         = "mistral.mistral-7b-instruct-v0:2"

SIMILARITY_THRESHOLD = 0.25   # lowered — RRF + reranker handle final filtering
RRF_K                = 60     # reciprocal rank fusion constant
RERANK_CANDIDATES    = 12     # how many fused candidates pass to the reranker
RERANK_WORKERS       = 6      # parallel Mistral calls for cross-encoder

embeddings_table = dynamodb.Table(EMBEDDINGS_TABLE_NAME)

_GREETING = re.compile(r'^(dear\s+\S.*?[,\n]|hi\s*\S*.*?[,\n]|hello\s*\S*.*?[,\n])', re.I)
_SIGN_OFF  = re.compile(r'(kind regards.*|best regards.*|yours sincerely.*|thank\s+you.*|thanks.*)$', re.I | re.S)


# ── Lambda handler ────────────────────────────────────────────────────────────

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        email_text = event.get('email_text') or event.get('body', '')
        if not email_text:
            raise ValueError("Missing email_text in event")

        intent = event.get('intent', '')
        top_k  = int(event.get('top_k', 5))

        # Step 1 — clean the raw query
        clean_query = _preprocess(email_text, intent)
        print(f"Query: raw_len={len(email_text)} clean_len={len(clean_query)} intent={intent!r}")

        # Step 2 — HyDE: embed a hypothetical answer, not the raw question
        hyde_doc = _hyde_expand(clean_query)
        print(f"HyDE doc (first 120 chars): {hyde_doc[:120]!r}")

        # Step 3 — embed the HyDE document
        query_embedding = _embed(hyde_doc)

        # Step 4 — load all KB documents (paginated scan)
        documents = _scan_all()
        print(f"Loaded {len(documents)} documents from knowledge base")

        if not documents:
            return {'statusCode': 200, 'retrieved_documents': [], 'num_documents': 0}

        # Step 5 — score: vector cosine + BM25
        contents   = [doc.get('content', '') for doc in documents]
        bm25       = BM25(contents)
        vec_scores  = _vector_scores(query_embedding, documents)
        bm25_scores = [bm25.score(clean_query, i) for i in range(len(documents))]

        # Step 6 — RRF fusion
        fused = _rrf_fuse(vec_scores, bm25_scores, k=RRF_K)

        # Step 7 — pre-filter by similarity threshold, take top candidates
        candidates = []
        for idx, rrf_score in fused[:RERANK_CANDIDATES]:
            sem = vec_scores[idx]
            if sem < SIMILARITY_THRESHOLD:
                continue
            candidates.append({**documents[idx], '_rrf_score': rrf_score, '_vec_score': sem})

        if not candidates:
            print(f"No candidates above threshold={SIMILARITY_THRESHOLD}")
            return {'statusCode': 200, 'retrieved_documents': [], 'num_documents': 0}

        # Step 8 — cross-encoder rerank
        ranked = _cross_encoder_rerank(clean_query, candidates)
        top_docs = ranked[:top_k]

        print(f"Retrieved {len(top_docs)} docs after rerank")
        for d in top_docs:
            print(f"  {d['doc_id']}: rerank={d['similarity_score']:.4f}")

        return {
            'statusCode':        200,
            'retrieved_documents': top_docs,
            'num_documents':     len(top_docs),
        }

    except ClientError as e:
        print(f"AWS Error: {e}")
        return {'statusCode': 500, 'error': str(e), 'retrieved_documents': []}
    except Exception as e:
        print(f"Error: {e}")
        return {'statusCode': 500, 'error': str(e), 'retrieved_documents': []}


# ── HyDE ──────────────────────────────────────────────────────────────────────

def _hyde_expand(query: str) -> str:
    """
    Generate a hypothetical document that would answer the query.
    Embedding a 2-3 sentence factual answer lands in the same embedding-space
    region as real KB documents — far better than embedding the short raw query.
    """
    prompt = (
        "You are an Irish health insurance assistant for Laya Healthcare. "
        "Write a 2–3 sentence factual answer to the following question exactly as "
        "it would appear in official Laya Healthcare documentation. "
        "Use precise insurance terminology. Do NOT mention that this is hypothetical.\n\n"
        f"Question: {query}\n\nAnswer:"
    )
    try:
        resp = bedrock_runtime.invoke_model(
            modelId=MISTRAL_MODEL_ID,
            body=json.dumps({
                "prompt":      f"<s>[INST] {prompt} [/INST]",
                "max_tokens":  150,
                "temperature": 0.0,
            }),
            contentType='application/json',
            accept='application/json',
        )
        return json.loads(resp['body'].read())['outputs'][0]['text'].strip()
    except Exception as e:
        print(f"HyDE failed, falling back to raw query: {e}")
        return query


# ── Embedding ─────────────────────────────────────────────────────────────────

def _embed(text: str) -> List[float]:
    if len(text) > 8000:
        text = text[:8000]
    resp = bedrock_runtime.invoke_model(
        modelId=TITAN_EMBEDDINGS_MODEL_ID,
        body=json.dumps({"inputText": text, "dimensions": 1024, "normalize": True}),
        contentType='application/json',
        accept='application/json',
    )
    emb = json.loads(resp['body'].read())['embedding']
    print(f"Embedded text (dim={len(emb)})")
    return emb


# ── DynamoDB scan (paginated) ─────────────────────────────────────────────────

def _scan_all() -> List[Dict[str, Any]]:
    docs, resp = [], embeddings_table.scan()
    docs.extend(resp.get('Items', []))
    while 'LastEvaluatedKey' in resp:
        resp = embeddings_table.scan(ExclusiveStartKey=resp['LastEvaluatedKey'])
        docs.extend(resp.get('Items', []))
    return docs


# ── Vector scoring ────────────────────────────────────────────────────────────

def _vector_scores(query_vec: List[float], documents: List[Dict[str, Any]]) -> List[float]:
    scores = []
    for doc in documents:
        raw = doc.get('embedding', '[]')
        try:
            vec = json.loads(raw) if isinstance(raw, str) else raw
            scores.append(_cosine(query_vec, vec))
        except Exception:
            scores.append(0.0)
    return scores


def _cosine(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot  = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    return dot / (mag_a * mag_b) if mag_a and mag_b else 0.0


# ── BM25 ──────────────────────────────────────────────────────────────────────

class BM25:
    """Lightweight BM25 implementation for keyword-based scoring."""
    def __init__(self, corpus: List[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tokenized  = [self._tok(d) for d in corpus]
        n               = len(self.tokenized)
        avgdl           = sum(len(d) for d in self.tokenized) / max(n, 1)
        self.avgdl      = avgdl
        df              = Counter(t for doc in self.tokenized for t in set(doc))
        self.idf        = {
            t: math.log((n - f + 0.5) / (f + 0.5) + 1)
            for t, f in df.items()
        }

    @staticmethod
    def _tok(text: str) -> List[str]:
        return re.findall(r'\b\w{2,}\b', text.lower())

    def score(self, query: str, doc_idx: int) -> float:
        doc  = self.tokenized[doc_idx]
        dl   = len(doc)
        tf   = Counter(doc)
        return sum(
            self.idf.get(t, 0) *
            (tf[t] * (self.k1 + 1)) /
            (tf[t] + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            for t in self._tok(query)
        )


# ── RRF fusion ────────────────────────────────────────────────────────────────

def _rrf_fuse(
    vec_scores: List[float],
    bm25_scores: List[float],
    k: int = 60,
) -> List[Tuple[int, float]]:
    """
    Reciprocal Rank Fusion: combine vector and BM25 rank lists.
    Returns list of (doc_index, rrf_score) sorted descending.
    """
    n = len(vec_scores)
    vec_order  = sorted(range(n), key=lambda i: vec_scores[i],  reverse=True)
    bm25_order = sorted(range(n), key=lambda i: bm25_scores[i], reverse=True)

    rrf: Dict[int, float] = {}
    for rank, idx in enumerate(vec_order):
        rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (k + rank + 1)
    for rank, idx in enumerate(bm25_order):
        rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (k + rank + 1)

    return sorted(rrf.items(), key=lambda x: x[1], reverse=True)


# ── Cross-encoder reranker ────────────────────────────────────────────────────

def _cross_encoder_rerank(
    query: str,
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Score each (query, document) pair jointly with Mistral 7B.
    Runs in parallel. Falls back to RRF score if Mistral call fails.
    """
    def score_one(doc: Dict[str, Any]) -> Dict[str, Any]:
        snippet = doc.get('content', '')[:400]
        prompt = (
            "You are scoring the relevance of an insurance knowledge base snippet to a customer query.\n"
            "Use Thought/Action/Observation to reason, then give a final score.\n\n"
            f"Query: {query}\n\n"
            f"Snippet: {snippet}\n\n"
            "Thought 1: What is the customer asking about?\n"
            "Action 1: IDENTIFY_QUERY_TOPIC\n"
            "Observation 1: <your observation>\n\n"
            "Thought 2: Does the snippet directly address this topic? What specific phrases match?\n"
            "Action 2: CHECK_SNIPPET_RELEVANCE\n"
            "Observation 2: <your observation>\n\n"
            "Thought 3: On a scale of 0-10, how relevant is this snippet?\n"
            "Action 3: ASSIGN_SCORE\n"
            "Observation 3: <your score reasoning>\n\n"
            'FINAL_ANSWER: {"score": <integer 0-10>, "reason": "<one sentence>"}'
        )
        try:
            resp = bedrock_runtime.invoke_model(
                modelId=MISTRAL_MODEL_ID,
                body=json.dumps({
                    "prompt":      f"<s>[INST] {prompt} [/INST]",
                    "max_tokens":  128,    # increased from 20 to accommodate ReAct trace
                    "temperature": 0.0,
                }),
                contentType='application/json',
                accept='application/json',
            )
            raw = json.loads(resp['body'].read())['outputs'][0]['text']
            scratchpad, json_str = extract_react_answer(raw)
            data = json.loads(json_str or _extract_json(raw))
            rerank_score = max(0.0, min(10.0, float(data.get('score', 5)))) / 10.0
            if scratchpad:
                print(f"Rerank trace [{doc.get('doc_id')}]: {scratchpad[:200]} | reason: {data.get('reason', '')}")
        except Exception as e:
            print(f"Reranker failed for {doc.get('doc_id')}: {e}")
            rerank_score = doc.get('_rrf_score', 0.0) * 5   # fallback: scale RRF

        # Final score: 50% reranker + 30% vector + 20% RRF
        final = round(
            0.5 * rerank_score +
            0.3 * doc.get('_vec_score', 0.0) +
            0.2 * min(doc.get('_rrf_score', 0.0) * 100, 1.0),
            4,
        )
        return {
            'doc_id':           doc.get('doc_id'),
            'doc_type':         doc.get('doc_type', 'unknown'),
            'content':          doc.get('content', ''),
            'similarity_score': final,
            'metadata':         doc.get('metadata', {}),
        }

    results = []
    with ThreadPoolExecutor(max_workers=RERANK_WORKERS) as ex:
        futures = {ex.submit(score_one, doc): doc for doc in candidates}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                print(f"Rerank future error: {e}")

    return sorted(results, key=lambda x: x['similarity_score'], reverse=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _preprocess(email_text: str, intent: str = '') -> str:
    text = email_text.strip()
    text = _GREETING.sub('', text).strip()
    text = _SIGN_OFF.sub('', text).strip()
    if intent:
        text = f"Insurance query about {intent.replace('_', ' ')}: {text}"
    return text[:8000]


def _extract_json(text: str) -> str:
    start = text.find('{')
    if start == -1:
        return '{}'
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return '{}'
