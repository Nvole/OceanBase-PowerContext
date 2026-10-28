"""Document API routes: upload, search, detail, delete."""
import json
import re
import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from ..database import get_db
from ..models import Document
from ..schemas import DocumentResponse, SearchResult, MessageResponse

router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB limit
ALLOWED_EXTENSIONS = {".md", ".txt"}


def parse_markdown_metadata(content: str, filename: str) -> dict:
    """Parse markdown file to extract title, type, tags, and paragraphs.
    
    Expects frontmatter-like headers:
    # Title
    type: reading|experiment|todo
    tags: tag1, tag2
    
    Body paragraphs separated by blank lines.
    """
    lines = content.split("\n")
    title = filename
    doc_type = "reading"
    tags = ""
    body_start = 0
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
        elif stripped.lower().startswith("type:"):
            doc_type = stripped.split(":", 1)[1].strip().lower()
        elif stripped.lower().startswith("tags:"):
            tags = stripped.split(":", 1)[1].strip()
        elif stripped == "" and i < 10:
            body_start = i + 1
    
    # Extract paragraphs from body
    body = "\n".join(lines[body_start:]).strip()
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', body) if p.strip()]
    
    return {
        "title": title[:500],
        "doc_type": doc_type[:50],
        "tags": tags[:1000],
        "content": content,
        "paragraphs": json.dumps(paragraphs, ensure_ascii=False),
    }


def sanitize_search_keyword(keyword: str) -> str:
    """Sanitize keyword to prevent SQL injection in LIKE queries.
    SQLAlchemy parameterized queries handle this, but we also escape wildcards.
    """
    # Escape SQL LIKE wildcards
    keyword = keyword.replace("\\", "\\\\")
    keyword = keyword.replace("%", "\\%")
    keyword = keyword.replace("_", "\\_")
    return keyword


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a Markdown or TXT file as a research document.
    
    Does not overwrite existing documents with the same filename.
    """
    # Validate extension
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Only {ALLOWED_EXTENSIONS} files are accepted")
    
    # Read content
    content_bytes = await file.read()
    if len(content_bytes) > MAX_FILE_SIZE:
        raise HTTPException(400, f"File too large (max {MAX_FILE_SIZE // 1024 // 1024}MB)")
    
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "File must be UTF-8 encoded")
    
    # Parse metadata
    meta = parse_markdown_metadata(content, file.filename)
    if meta['doc_type'] not in {'reading', 'experiment', 'todo'}:
        raise HTTPException(400, 'type must be reading, experiment or todo')
    
    # Check for duplicate filename - do NOT overwrite
    existing = db.query(Document).filter(Document.source_file == file.filename).first()
    if existing:
        # Append a suffix to differentiate
        counter = 1
        while True:
            new_name = f"{os.path.splitext(file.filename)[0]}_{counter}{ext}"
            if not db.query(Document).filter(Document.source_file == new_name).first():
                meta["source_file"] = new_name
                break
            counter += 1
    else:
        meta["source_file"] = file.filename
    
    doc = Document(**meta)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    return doc


@router.get("/search", response_model=list[SearchResult])
def search_documents(
    keyword: str = Query(..., min_length=1, max_length=200),
    doc_type: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Search documents by keyword with optional type/tag filtering.
    
    All filtering is done by the database via parameterized queries.
    Returns matched paragraphs with source info.
    """
    safe_keyword = sanitize_search_keyword(keyword)
    
    # Build query - all matching is done by the database engine
    query = db.query(Document)
    
    # Keyword search: match in title, content, or tags
    like_pattern = f"%{safe_keyword}%"
    query = query.filter(
        or_(
            Document.title.like(like_pattern, escape="\\"),
            Document.content.like(like_pattern, escape="\\"),
            Document.tags.like(like_pattern, escape="\\"),
        )
    )
    
    # Type filter
    if doc_type:
        query = query.filter(Document.doc_type == doc_type)
    
    # Tag filter
    if tag:
        safe_tag = sanitize_search_keyword(tag)
        query = query.filter(Document.tags.like(f"%{safe_tag}%", escape="\\"))
    
    # Pagination
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()
    
    # Extract matched paragraphs
    search_results = []
    for doc in results:
        paragraphs = json.loads(doc.paragraphs) if doc.paragraphs else [doc.content[:200]]
        matched = [p for p in paragraphs if keyword.lower() in p.lower()]
        if not matched:
            matched = paragraphs[:1] if paragraphs else [doc.content[:200]]
        
        search_results.append(SearchResult(
            id=doc.id,
            title=doc.title,
            doc_type=doc.doc_type,
            tags=doc.tags,
            source_file=doc.source_file,
            matched_paragraph=matched[0] if matched else "",
            created_at=doc.created_at,
        ))
    
    return search_results


@router.get("/{doc_id}", response_model=DocumentResponse)
def get_document(doc_id: int, db: Session = Depends(get_db)):
    """Get a single document by ID."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@router.delete("/{doc_id}", response_model=MessageResponse)
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    """Delete a document by ID."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    
    db.delete(doc)
    db.commit()
    return MessageResponse(message=f"Document {doc_id} deleted")


@router.get("/", response_model=list[DocumentResponse])
def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List all documents."""
    offset = (page - 1) * page_size
    return db.query(Document).order_by(Document.created_at.desc()).offset(offset).limit(page_size).all()
