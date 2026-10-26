"""Read-only provider smoke checks. Explicit opt-in, never sends email or refunds."""

import os

import httpx
import pytest

from app.config import settings


@pytest.mark.live
def test_groq_model_access():
    if not os.getenv("RUN_LIVE_TESTS") or not settings().groq_api_key:
        pytest.skip("Set RUN_LIVE_TESTS=1 and GROQ_API_KEY")
    response = httpx.get(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": "Bearer " + settings().groq_api_key},
        timeout=20,
    )
    response.raise_for_status()
    assert settings().groq_model in {model["id"] for model in response.json()["data"]}


@pytest.mark.live
def test_real_local_semantic_embeddings(monkeypatch):
    if not os.getenv("RUN_EMBEDDING_TESTS"):
        pytest.skip("Set RUN_EMBEDDING_TESTS=1 with the embeddings extra installed and model downloaded")
    from app.services.knowledge import embed

    monkeypatch.setattr(settings(), "demo_mode", False)
    vectors = embed(
        ["refund for a duplicate invoice", "return money charged twice", "a yellow banana grows on a tree"]
    )
    assert all(len(vector) == 384 for vector in vectors)

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))

    assert dot(vectors[0], vectors[1]) > dot(vectors[0], vectors[2])
