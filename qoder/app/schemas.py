"""Pydantic schemas for API request/response."""
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import datetime


class DocumentCreate(BaseModel):
    title: str = Field(..., max_length=500)
    doc_type: str = Field(..., max_length=50)
    tags: Optional[str] = Field(None, max_length=1000)
    content: str
    source_file: str = Field(..., max_length=500)
    paragraphs: Optional[str] = None


class DocumentResponse(BaseModel):
    id: int
    title: str
    doc_type: str
    tags: Optional[str]
    content: str
    source_file: str
    paragraphs: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class SearchResult(BaseModel):
    id: int
    title: str
    doc_type: str
    tags: Optional[str]
    source_file: str
    matched_paragraph: str
    created_at: Optional[datetime]


class SearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=200)
    doc_type: Optional[str] = None
    tag: Optional[str] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class MessageResponse(BaseModel):
    message: str
    success: bool = True
