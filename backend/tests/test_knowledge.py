from sqlalchemy import select

from app.models import Document, Job
from app.services.jobs import process_job
from app.services.knowledge import extract, split_text
from conftest import sign_in


def test_real_upload_index_search_delete_and_tenant_filter(env, client):
    result = client.post(
        "/api/v1/documents",
        files={
            "file": (
                "policy.md",
                b"Refunds are permitted within fourteen days. Only workspace owners may approve a refund.",
                "text/markdown",
            )
        },
    )
    doc_id = result.json()["id"]
    with env["factory"]() as db:
        identifier = db.scalar(select(Job.id).where(Job.entity_id == doc_id))
    process_job(identifier, env["workspace"])
    result = client.post("/api/v1/search", json={"query": "refund policy"})
    assert result.status_code == 200 and result.json()["items"]
    assert result.json()["items"][0]["document_id"] == doc_id
    sign_in(client, "other@example.com")
    assert not client.post("/api/v1/search", json={"query": "refund policy"}).json()["items"]
    assert client.get(f"/api/v1/documents/{doc_id}/source").status_code == 404
    sign_in(client)
    client.delete("/api/v1/documents/" + doc_id)
    assert not client.post("/api/v1/search", json={"query": "refund policy"}).json()["items"]


def test_bounded_chunking_and_malformed_uploads(env, client):
    pieces = split_text(" ".join("word" + str(i) for i in range(500)))
    assert max(len(p.split()) for p in pieces) <= 200
    assert pieces[0].split()[-32:] == pieces[1].split()[:32]
    assert (
        client.post(
            "/api/v1/documents", files={"file": ("bad.pdf", b"not pdf", "application/pdf")}
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/api/v1/documents", files={"file": ("bad.exe", b"not allowed", "application/octet-stream")}
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/api/v1/documents/drive/import", json={"file_id": "safe-file", "publish_to_workspace": False}
        ).status_code
        == 400
    )


def test_failed_ingestion_is_inspectable(env, client):
    result = client.post("/api/v1/documents", files={"file": ("empty.txt", b"  ", "text/plain")})
    identifier = result.json()["id"]
    with env["factory"]() as db:
        job_id = db.scalar(select(Job.id).where(Job.entity_id == identifier))
    process_job(job_id, env["workspace"])
    with env["factory"]() as db:
        assert db.get(Document, identifier).status == "failed"
        assert "OCR" in db.get(Document, identifier).error
        assert db.get(Job, job_id).status == "dead_letter"


def test_empty_text_reports_ocr_reason():
    import pytest

    with pytest.raises(ValueError, match="OCR"):
        extract(b" ", "text/plain")
