from app.parsers import chunk_text
from app.security import detect_identifiers, sanitize_filename


def test_identifier_detection() -> None:
    assert "email address" in detect_identifiers("Contact test.person@example.com")
    assert "US Social Security number" in detect_identifiers("Synthetic identifier 123-45-6789")
    assert detect_identifiers("Protocol SYN-101 contains no direct identifiers") == []


def test_filename_is_sanitized() -> None:
    assert sanitize_filename("../../unsafe protocol?.pdf") == "unsafe_protocol_.pdf"


def test_chunk_text_preserves_content() -> None:
    source = "alpha paragraph\n\n" + ("beta " * 20) + "\n\ngamma"
    chunks = chunk_text(source, chunk_size=40)
    assert len(chunks) > 1
    assert "alpha paragraph" in chunks[0]
    assert "gamma" in chunks[-1]
