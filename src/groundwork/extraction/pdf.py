"""PDF text extraction for resume uploads (BUILD_PLAN.md Slice 2 - scope
extended from "raw text only" once file upload was actually needed).

Deliberately minimal: pull whatever text layer the PDF has and hand it to
the same extract_profile() utility that already handles raw text - no
PDF-specific logic downstream of this. A PDF with no extractable text (a
scanned/image-only resume, for example) is a real failure mode worth a
clear error, not a silent empty string sent to the LLM.
"""

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract all text from a PDF's pages, concatenated in reading order.

    Raises ValueError if the PDF can't be read (corrupted, encrypted) or
    has no extractable text - both are real possibilities with resume
    uploads, not edge cases to wave away.
    """
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except PdfReadError as exc:
        raise ValueError(f"Couldn't read PDF: {exc}") from exc

    if reader.is_encrypted:
        raise ValueError("PDF is password-protected - remove the password and try again")

    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()

    if not text:
        raise ValueError(
            "No extractable text found in PDF - it may be a scanned image "
            "with no text layer"
        )

    return text
