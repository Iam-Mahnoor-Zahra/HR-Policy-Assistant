"""Shared helpers for the Chroma vector store (used by ingest.py and qa.py)."""
import os

from langchain_chroma import Chroma

PERSIST_DIR = os.getenv("CHROMA_DIR", "chroma_db")
COLLECTION = "hr_policies"
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


def get_embeddings():
    # Imported here so tests and other scripts do not load the model unless needed.
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=EMBED_MODEL)


def get_store(embeddings=None):
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=embeddings or get_embeddings(),
        persist_directory=PERSIST_DIR,
        collection_metadata={"hnsw:space": "cosine"},  # scores become cosine distance
    )
