"""SQLAlchemy models for research documents."""
from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from sqlalchemy.sql import func
from .database import Base


class Document(Base):
    """A research document (reading note, experiment record, or todo)."""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False, index=True)
    doc_type = Column(String(50), nullable=False, index=True)  # reading, experiment, todo
    tags = Column(String(1000), nullable=True)  # comma-separated tags
    content = Column(Text, nullable=False)  # full text content
    source_file = Column(String(500), nullable=False)  # original filename
    paragraphs = Column(Text, nullable=True)  # JSON array of paragraphs for display
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_type_tags", "doc_type", "tags"),
    )

    def __repr__(self):
        return f"<Document(id={self.id}, title='{self.title}', type='{self.doc_type}')>"
