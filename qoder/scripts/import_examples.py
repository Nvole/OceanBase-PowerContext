"""Import example documents from the examples/ directory into the database."""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, init_db, USE_SQLITE
from app.models import Document
from app.routers.documents import parse_markdown_metadata


def import_examples():
    """Import all example files from examples/ directory."""
    init_db()
    db = SessionLocal()
    
    examples_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
    
    if not os.path.exists(examples_dir):
        print(f"ERROR: examples directory not found: {examples_dir}")
        return
    
    files = [f for f in os.listdir(examples_dir) if f.endswith(('.md', '.txt'))]
    
    print(f"Database mode: {'SQLite (dev)' if USE_SQLITE else 'seekdb (MySQL)'}")
    print(f"Found {len(files)} example files to import")
    print("-" * 50)
    
    imported = 0
    for filename in sorted(files):
        filepath = os.path.join(examples_dir, filename)
        
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check if already imported
        existing = db.query(Document).filter(Document.source_file == filename).first()
        if existing:
            print(f"SKIP: {filename} (already imported as ID {existing.id})")
            continue
        
        meta = parse_markdown_metadata(content, filename)
        meta["source_file"] = filename
        
        doc = Document(**meta)
        db.add(doc)
        db.commit()
        db.refresh(doc)
        
        print(f"OK: {filename} -> ID {doc.id}, type={doc.doc_type}, title={doc.title}")
        imported += 1
    
    print("-" * 50)
    print(f"Imported {imported} new documents, total in DB: {db.query(Document).count()}")
    
    # Show a sample
    sample = db.query(Document).first()
    if sample:
        print(f"\nSample document:")
        print(f"  ID: {sample.id}")
        print(f"  Title: {sample.title}")
        print(f"  Type: {sample.doc_type}")
        print(f"  Tags: {sample.tags}")
        print(f"  Source: {sample.source_file}")
        print(f"  Content preview: {sample.content[:100]}...")
    
    db.close()


if __name__ == "__main__":
    import_examples()
