import hashlib
from pathlib import PurePath

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Chunk, Connection, Document, DocumentVersion, now, uid
from app.dto import DocumentOut, PageOut
from app.schemas import DriveImport, SearchInput
from app.security import Identity, audit, database, identity, tenant_get
from app.serialization import page, public
from app.services.jobs import enqueue
from app.services.knowledge import MIME, search
from app.services.providers import Composio
from app.services.storage import storage

router = APIRouter(tags=["knowledge"])


def new_document(db, who, name, data, mime, **kwargs):
    identifier = uid()
    key = f"{who.workspace_id}/{identifier}/v1"
    storage().put(key, data)
    doc = Document(
        id=identifier,
        workspace_id=who.workspace_id,
        uploaded_by=who.user.id,
        name=name[:255],
        storage_key=key,
        mime_type=mime,
        size=len(data),
        content_hash=hashlib.sha256(data).hexdigest(),
        **kwargs,
    )
    db.add(doc)
    db.flush()
    db.add(
        DocumentVersion(
            workspace_id=who.workspace_id,
            document_id=doc.id,
            version=1,
            name=doc.name,
            mime_type=mime,
            storage_key=key,
            content_hash=doc.content_hash,
        )
    )
    enqueue(db, who.workspace_id, "index", doc.id)
    audit(db, who, "document.created", doc.id)
    return doc


@router.get("/documents", response_model=PageOut[DocumentOut])
def documents(
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = None,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    rows, next_cursor = page(db, Document, who.workspace_id, limit, cursor, [Document.deleted_at.is_(None)])
    return {
        "items": [public(d, exclude=["storage_key", "content_hash"]) for d in rows],
        "next_cursor": next_cursor,
    }


@router.post("/documents", status_code=202, response_model=DocumentOut)
async def upload(
    file: UploadFile = File(...),
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    name = PurePath(file.filename or "document").name
    suffix = PurePath(name).suffix.lower()
    if suffix not in MIME:
        raise HTTPException(415, "Supported files: PDF, DOCX, TXT, Markdown")
    data = await file.read(25 * 1024 * 1024 + 1)
    await file.close()
    if not data or len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "File is empty or exceeds 25 MB")
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise HTTPException(415, "File is not a PDF")
    if suffix == ".docx" and not data.startswith(b"PK"):
        raise HTTPException(415, "File is not a DOCX")
    return public(new_document(db, who, name, data, MIME[suffix]), exclude=["storage_key", "content_hash"])


@router.get("/documents/drive/files")
def drive_files(
    query: str = Query("", max_length=150),
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    connection = db.scalar(
        select(Connection).where(
            Connection.workspace_id == who.workspace_id,
            Connection.user_id == who.user.id,
            Connection.provider == "googledrive",
            Connection.status == "active",
        )
    )
    if not connection:
        raise HTTPException(400, "Connect Google Drive first")
    Composio().account(connection)
    return {"items": Composio().drive_files(connection, query)}


@router.post("/documents/drive/import", status_code=202)
def drive_import(
    body: DriveImport,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    if not body.publish_to_workspace:
        raise HTTPException(400, "Confirm publication to shared workspace knowledge")
    connection = db.scalar(
        select(Connection).where(
            Connection.workspace_id == who.workspace_id,
            Connection.user_id == who.user.id,
            Connection.provider == "googledrive",
            Connection.status == "active",
        )
    )
    if not connection:
        raise HTTPException(400, "Connect Google Drive first")
    Composio().account(connection)
    meta, content = Composio().drive_download(connection, body.file_id)
    if meta["mimeType"] not in MIME.values():
        raise HTTPException(415, "Unsupported Drive document type")
    doc = new_document(
        db,
        who,
        meta["name"],
        content,
        meta["mimeType"],
        source_id=body.file_id,
        source_url=meta.get("webViewLink", "https://drive.google.com/file/d/" + body.file_id),
        connection_id=connection.id,
    )
    return public(doc, exclude=["storage_key", "content_hash"])


@router.get("/documents/{document_id}/source")
def source(
    document_id: str,
    version: int | None = Query(None, ge=1),
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    doc = tenant_get(db, Document, document_id, who.workspace_id)
    if doc.deleted_at:
        raise HTTPException(404, "Source was removed")
    historical = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.workspace_id == who.workspace_id,
            DocumentVersion.document_id == doc.id,
            DocumentVersion.version == (version or doc.version),
        )
    )
    if not historical and version and version != doc.version:
        raise HTTPException(404, "Source version is unavailable")
    snapshot = historical or doc
    from urllib.parse import quote

    return Response(
        storage().get(snapshot.storage_key),
        media_type=snapshot.mime_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(snapshot.name),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/documents/{document_id}")
def remove(
    document_id: str,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    doc = tenant_get(db, Document, document_id, who.workspace_id)
    if doc.uploaded_by != who.user.id and who.membership.role != "owner":
        raise HTTPException(403, "Only the uploader or an owner can remove a document")
    doc.deleted_at, doc.status = now(), "deleted"
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id, Chunk.workspace_id == who.workspace_id))
    audit(db, who, "document.deleted", doc.id)
    return {"ok": True}


@router.post("/documents/{document_id}/refresh", status_code=202)
def refresh(
    document_id: str,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    doc = tenant_get(db, Document, document_id, who.workspace_id)
    if doc.deleted_at:
        raise HTTPException(404, "Document was removed")
    if doc.uploaded_by != who.user.id and who.membership.role != "owner":
        raise HTTPException(403, "Only the uploader or owner can reindex")
    pending = db.scalar(
        select(Document.id).where(Document.id == doc.id, Document.status.in_(["queued", "indexing"]))
    )
    if pending:
        raise HTTPException(409, "Document is already being indexed")
    if doc.source_id:
        connection = tenant_get(db, Connection, doc.connection_id, who.workspace_id)
        if connection.user_id != who.user.id or connection.status != "active":
            raise HTTPException(403, "Only the connected Drive owner can refresh this snapshot")
        Composio().account(connection)
        meta, content = Composio().drive_download(connection, doc.source_id)
        if meta["mimeType"] not in MIME.values():
            raise HTTPException(415, "Unsupported Drive document type")
        doc.version += 1
        doc.storage_key = f"{who.workspace_id}/{doc.id}/v{doc.version}"
        storage().put(doc.storage_key, content)
        doc.size, doc.content_hash = len(content), hashlib.sha256(content).hexdigest()
        doc.name, doc.mime_type = meta["name"], meta["mimeType"]
        db.add(
            DocumentVersion(
                workspace_id=who.workspace_id,
                document_id=doc.id,
                version=doc.version,
                name=doc.name,
                mime_type=doc.mime_type,
                storage_key=doc.storage_key,
                content_hash=doc.content_hash,
            )
        )
    doc.status, doc.error = "queued", None
    enqueue(db, who.workspace_id, "index", doc.id)
    audit(db, who, "document.refreshed", doc.id)
    return {"ok": True}


@router.post("/search")
def retrieve(
    body: SearchInput,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    return {"items": search(db, who.workspace_id, body.query)}
