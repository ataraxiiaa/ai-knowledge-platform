import math
import uuid

import pytest

from app.api.documents import require_vector_database
from app.core.config import settings
from app.main import app
from app.models.chunks import Chunk
from app.models.documents import Document
from app.services.bm25 import BM25Index, tokenize
from app.services import retrieval
from test_ingestion import owner


def test_tokenization_identifiers_numbers_and_unicode():
    assert tokenize("HNSW ef_search GPU-42 1.2 CAFÉ cafe\u0301 ＡＢＣ") == [
        "hnsw", "ef", "search", "gpu", "42", "1", "2", "café", "café", "abc"]
    assert tokenize("?!___") == []


def test_formula_matches_hand_calculation():
    index = BM25Index(["cat cat dog", "dog"])
    # N=2, df(cat)=1, tf=2, dl=3, avgdl=2, k1=1.2, b=.75.
    expected = math.log(2) * (2 * 2.2) / (2 + 1.2 * (.25 + .75 * 3 / 2))
    assert index.scores("cat") == pytest.approx([expected, 0])
    assert index.scores("cat CAT cat") == index.scores("cat")


def test_rare_terms_length_normalization_and_saturation():
    index = BM25Index(["rare common", "common common", "common common"])
    assert index.scores("rare")[0] > index.scores("common")[0]
    index = BM25Index(["term", "term filler filler"])
    assert index.scores("term")[0] > index.scores("term")[1]
    scores = BM25Index(["term", "term term term term"], b=0).scores("term")
    assert scores[0] < scores[1] < 4 * scores[0]


def test_empty_and_no_match_are_zero():
    assert BM25Index([]).scores("term") == []
    assert BM25Index(["", "!!!"]).scores("term") == [0, 0]
    assert BM25Index(["dog"]).scores("puppy") == [0]
    assert BM25Index(["dog"]).scores("?!") == [0]


@pytest.mark.parametrize("k1,b", [(0, .75), (float("nan"), .75), (1.2, -1), (1.2, float("inf"))])
def test_invalid_parameters(k1, b):
    with pytest.raises(ValueError):
        BM25Index(["text"], k1=k1, b=b)


def add_document(db, workspace, text, *, status="ready", chunk_id=None):
    document = Document(workspace_id=uuid.UUID(workspace), filename="paper.pdf", status=status)
    db.add(document)
    db.flush()
    chunk = Chunk(id=chunk_id or uuid.uuid4(), document_id=document.id, content=text, page=7,
                  chunk_index=0, embedding=[1.0] + [0.0] * 383, chunk_metadata={"test": True})
    db.add(chunk)
    db.commit()
    return chunk


@pytest.fixture
def bm25_client(client, monkeypatch):
    app.dependency_overrides[require_vector_database] = lambda: None
    monkeypatch.setattr(retrieval, "embed_texts", lambda *_: pytest.fail("BM25 must not embed queries"))
    return client


def test_endpoint_scopes_before_scoring_and_preserves_sources(bm25_client, db_session):
    client = bm25_client
    headers, workspace = owner(client)
    other_headers, other = owner(client, "other@example.com")
    own = add_document(db_session, workspace, "HNSW GPU-42")
    url = f"/workspaces/{workspace}/search"
    request = {"query": "gpu-42", "method": "bm25", "top_k": 1}
    first = client.post(url, headers=headers, json=request).json()
    add_document(db_session, other, "GPU-42 GPU-42 GPU-42")
    add_document(db_session, workspace, "GPU-42", status="failed")
    add_document(db_session, workspace, "GPU-42", status="processing")
    response = client.post(url, headers=headers, json=request)
    assert response.status_code == 200 and response.json() == first  # DF/avgdl also isolated.
    hit = first[0]
    assert hit["chunk_id"] == str(own.id) and hit["document_id"] == str(own.document_id)
    assert hit["page"] == 7 and hit["filename"] == "paper.pdf" and hit["metadata"] == {"test": True}
    assert hit["similarity"] is None and hit["bm25_score"] > 0 and hit["retrieval_method"] == "bm25"
    assert client.post(url, headers=other_headers, json=request).status_code == 404
    assert client.post(url, json=request).status_code == 401


def test_ties_no_matches_and_deleted_chunks(bm25_client, db_session):
    client = bm25_client
    headers, workspace = owner(client)
    high = add_document(db_session, workspace, "HNSW", chunk_id=uuid.UUID(int=2))
    low = add_document(db_session, workspace, "HNSW", chunk_id=uuid.UUID(int=1))
    url = f"/workspaces/{workspace}/search"
    result = client.post(url, headers=headers, json={"query": "HNSW", "method": "bm25"}).json()
    assert [r["chunk_id"] for r in result] == [str(low.id), str(high.id)]
    for query in ("unknown123", "???"):
        assert client.post(url, headers=headers, json={"query": query, "method": "bm25"}).json() == []
    assert client.delete(f"/workspaces/{workspace}/documents/{low.document_id}", headers=headers).status_code == 204
    result = client.post(url, headers=headers, json={"query": "hnsw", "method": "bm25"}).json()
    assert [r["chunk_id"] for r in result] == [str(high.id)]


def test_limit_fails_instead_of_truncating_corpus(bm25_client, db_session, monkeypatch):
    headers, workspace = owner(bm25_client)
    add_document(db_session, workspace, "one")
    add_document(db_session, workspace, "two")
    monkeypatch.setattr(settings, "BM25_MAX_CHUNKS", 1)
    response = bm25_client.post(f"/workspaces/{workspace}/search", headers=headers,
                               json={"query": "one", "method": "bm25"})
    assert response.status_code == 503 and "limit" in response.json()["detail"]


@pytest.mark.parametrize("payload", [{"query": " " , "method": "bm25"},
                                     {"query": "term", "method": "unknown"},
                                     {"query": "term", "method": "bm25", "top_k": 21}])
def test_request_validation(bm25_client, payload):
    headers, workspace = owner(bm25_client)
    assert bm25_client.post(f"/workspaces/{workspace}/search", headers=headers, json=payload).status_code == 422
