"""
data_ingestion.py - Offline ingestion script for company rules RAG system
Scans ./data directory, converts Word/PDF to Markdown, chunks with semantic parsing,
and stores BGE embeddings in ChromaDB (local vector database).
"""

import sys
import io
import os
from pathlib import Path
from typing import List, Optional

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Centralized configuration (loads .env via config.py)
import config

# LlamaIndex core imports
from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.core.schema import MetadataMode

# ChromaDB vector store
import chromadb
from llama_index.vector_stores.chroma import ChromaVectorStore

# Embedding model
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

# Document parsing
import docx

# Configuration (read from .env via config.py; overridable for tests)
DATA_DIR = config.DATA_DIR
CHROMA_PERSIST_DIR = config.CHROMA_PERSIST_DIR
COLLECTION_NAME = config.COLLECTION_NAME

# Embedding model config
EMBED_MODEL_NAME = config.EMBED_MODEL_NAME
EMBED_DIM = config.EMBED_DIM


def docx_to_text(file_path: str) -> str:
    """Extract text from DOCX file using python-docx."""
    doc = docx.Document(file_path)
    text_parts = []
    
    for para in doc.paragraphs:
        # Handle headings
        if para.style.name.startswith('Heading'):
            level = para.style.name.split(' ')[-1]
            try:
                level = int(level)
                text_parts.append(f"{'#' * (level + 1)} {para.text}")
            except ValueError:
                text_parts.append(f"## {para.text}")
        else:
            text_parts.append(para.text)
    
    # Handle tables
    for table in doc.tables:
        for row in table.rows:
            row_text = ' | '.join(cell.text for cell in row.cells)
            text_parts.append(f"| {row_text} |")
        text_parts.append("")
    
    return '\n'.join(text_parts)


def convert_to_markdown(file_path: str) -> List[Document]:
    """Convert DOCX/MD files to Markdown format documents."""
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()
    
    try:
        if suffix == ".docx":
            text_content = docx_to_text(file_path)
            # Add title from filename
            text_content = f"# {file_path.stem}\n\n{text_content}"
            doc = Document(text=text_content)
            doc.metadata["source_file"] = str(file_path)
            doc.metadata["file_type"] = suffix
            return [doc]
        elif suffix == ".md":
            # Handle markdown files directly
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            doc = Document(text=content)
            doc.metadata["source_file"] = str(file_path)
            doc.metadata["file_type"] = suffix
            return [doc]
        else:
            print(f"Skipping unsupported file type: {file_path}")
            return []
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return []


def scan_data_directory(data_dir: str) -> List[Document]:
    """Scan data directory for supported files and convert to documents."""
    data_path = Path(data_dir)
    all_documents = []
    
    supported_extensions = [".docx", ".pdf", ".md"]
    
    for ext in supported_extensions:
        for file_path in data_path.glob(f"*{ext}"):
            print(f"Processing: {file_path}")
            docs = convert_to_markdown(str(file_path))
            all_documents.extend(docs)
    
    return all_documents


def create_semantic_chunks(documents: List[Document]) -> List:
    """Parse documents into semantic chunks using MarkdownNodeParser."""
    parser = MarkdownNodeParser(
        include_metadata=True,
        include_prev_next_rel=True,
        metadata_mode=MetadataMode.ALL
    )
    
    nodes = parser.get_nodes_from_documents(documents)
    print(f"Created {len(nodes)} semantic chunks from {len(documents)} documents")
    return nodes


def setup_vector_store():
    """Initialize ChromaDB vector store."""
    # Ensure persist directory exists
    os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
    
    # Initialize ChromaDB client
    chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    
    # Get or create collection
    try:
        collection = chroma_client.get_collection(name=COLLECTION_NAME)
        print(f"Using existing collection '{COLLECTION_NAME}'")
    except:
        collection = chroma_client.create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        print(f"Created new collection '{COLLECTION_NAME}'")
    
    return collection, chroma_client


def setup_embedding_model():
    """Initialize BGE embedding model for Chinese text."""
    embed_model = HuggingFaceEmbedding(
        model_name=EMBED_MODEL_NAME,
        query_instruction="为这个句子生成表示以用于检索相关文章：",
        text_instruction="把这段文章转化成一个向量表示：",
        embed_batch_size=32
    )
    return embed_model


def ingest_to_database():
    """Main ingestion pipeline."""
    print("=" * 60)
    print("Starting RAG Data Ingestion Pipeline")
    print("=" * 60)
    
    # Step 1: Setup embedding model
    print("\n[1/5] Initializing BGE embedding model...")
    embed_model = setup_embedding_model()
    print(f"Embedding model loaded: {EMBED_MODEL_NAME} (dim={EMBED_DIM})")
    
    # Step 2: Scan and convert documents
    print(f"\n[2/5] Scanning {DATA_DIR} for documents...")
    documents = scan_data_directory(DATA_DIR)
    if not documents:
        print("No documents found in ./data directory!")
        print("Please add .docx or .pdf files to the data directory.")
        sys.exit(1)
    print(f"Converted {len(documents)} documents to Markdown format")
    
    # Step 3: Create semantic chunks
    print("\n[3/5] Creating semantic chunks with MarkdownNodeParser...")
    nodes = create_semantic_chunks(documents)
    
    # Step 4: Setup ChromaDB vector store
    print("\n[4/5] Initializing ChromaDB vector store...")
    collection, chroma_client = setup_vector_store()
    vector_store = ChromaVectorStore(chroma_collection=collection)
    print(f"ChromaDB collection '{COLLECTION_NAME}' ready at {CHROMA_PERSIST_DIR}")
    
    # Step 5: Build and persist index
    print("\n[5/5] Building vector index and storing embeddings...")
    
    # Create storage context with vector store
    storage_context = StorageContext.from_defaults(
        vector_store=vector_store
    )
    
    # Create index with storage context
    index = VectorStoreIndex(
        nodes=nodes,
        storage_context=storage_context,
        embed_model=embed_model,
        show_progress=True
    )
    
    # Force persist
    print("Persisting data to disk...")
    
    # Verify data was stored
    collection_count = collection.count()
    print(f"Verification: Collection now contains {collection_count} items")
    
    print("\n" + "=" * 60)
    print("[OK] Ingestion Complete!")
    print(f"   - Documents processed: {len(documents)}")
    print(f"   - Chunks created: {len(nodes)}")
    print(f"   - Vector dimensions: {EMBED_DIM}")
    print(f"   - Collection: {COLLECTION_NAME}")
    print(f"   - Persist dir: {CHROMA_PERSIST_DIR}")
    print("=" * 60)
    
    return index, vector_store


if __name__ == "__main__":
    ingest_to_database()
