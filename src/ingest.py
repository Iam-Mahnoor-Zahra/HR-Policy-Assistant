"""Build the knowledge base: read data/policies/*.md, split by section, embed, store in Chroma.

Run from the project root:
    python -m src.ingest
Run it again whenever you add or change a policy file.
"""
import re
from pathlib import Path

from langchain_core.documents import Document

from src.vectorstore import get_embeddings, get_store

POLICY_DIR = Path("data/policies")

H1 = re.compile(r"^#\s+(.+)$")                   # "# Leave Policy"
H2 = re.compile(r"^##\s+(\d+)\.\s+(.+)$")        # "## 4. Carry-Forward and Encashment"
H3 = re.compile(r"^###\s+(\d+\.\d+)\s+(.+)$")    # "### 4.2 Carry-forward limit"


def parse_policy(path: Path) -> list[Document]:
    """Turn one policy file into one chunk per numbered subsection (### heading)."""
    policy_name = path.stem.replace("_", " ").title()
    group = ""
    current = None
    sections = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if m := H1.match(line):
            policy_name = m.group(1).strip()
        elif m := H2.match(line):
            group = m.group(2).strip()
        elif m := H3.match(line):
            if current:
                sections.append(current)
            current = {"number": m.group(1), "title": m.group(2).strip(), "group": group, "lines": []}
        elif current is not None and line.strip() and not line.startswith("#"):
            current["lines"].append(line.strip())
    if current:
        sections.append(current)

    docs = []
    for s in sections:
        body = " ".join(s["lines"])
        header = f"{policy_name} | Section {s['number']} {s['title']} | {s['group']}"
        docs.append(
            Document(
                page_content=f"{header}\n{body}",
                metadata={
                    "policy_name": policy_name,
                    "file_name": path.name,
                    "section": s["number"],
                    "title": s["title"],
                    "group": s["group"],
                },
            )
        )
    return docs


def load_chunks(policy_dir: Path = POLICY_DIR) -> list[Document]:
    docs = []
    for path in sorted(Path(policy_dir).glob("*.md")):
        docs.extend(parse_policy(path))
    return docs


def main():
    docs = load_chunks()
    if not docs:
        raise SystemExit("No policy chunks found. Check that data/policies/*.md exists.")
    print(f"Found {len(docs)} chunks in {len({d.metadata['file_name'] for d in docs})} files.")

    embeddings = get_embeddings()  # first run downloads the embedding model
    store = get_store(embeddings)
    try:
        store.delete_collection()  # start fresh so re-running never duplicates chunks
    except Exception:
        pass
    store = get_store(embeddings)
    ids = [f"{d.metadata['file_name']}::{d.metadata['section']}" for d in docs]
    store.add_documents(docs, ids=ids)
    print("Knowledge base built in the 'chroma_db' folder.")


if __name__ == "__main__":
    main()
