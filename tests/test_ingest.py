from pathlib import Path

from src.ingest import load_chunks


def test_chunks_are_created_from_all_policy_files():
    docs = load_chunks(Path("data/policies"))
    files = {d.metadata["file_name"] for d in docs}
    assert len(files) >= 5
    assert len(docs) >= 30


def test_every_chunk_has_citation_metadata():
    for d in load_chunks(Path("data/policies")):
        for key in ("policy_name", "file_name", "section", "title"):
            assert d.metadata[key], f"missing {key}"
        assert d.page_content.strip()


def test_carry_forward_section_is_found():
    docs = load_chunks(Path("data/policies"))
    match = [
        d for d in docs
        if d.metadata["file_name"] == "leave_policy.md" and d.metadata["section"] == "4.2"
    ]
    assert len(match) == 1
    assert match[0].metadata["policy_name"] == "Leave Policy"
    assert "5 unused annual leave days" in match[0].page_content
