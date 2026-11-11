"""PDF text extraction and page rendering.
Scanned/image-only PDFs yield no text and are reported clearly.
Page image rendering via pypdfium2 is optional."""
from pathlib import Path
from pypdf import PdfReader


def extract_text(path):
    """Extract text from PDF along with (page, start_offset, end_offset) mapping."""
    reader = PdfReader(str(path))
    parts = []
    page_map = []
    current_offset = 0
    for idx, page in enumerate(reader.pages, start=1):
        ptxt = (page.extract_text() or "").strip()
        if not ptxt:
            continue
        if parts:
            current_offset += 2  # for "\n\n"
        start_offset = current_offset
        parts.append(ptxt)
        current_offset += len(ptxt)
        end_offset = current_offset
        page_map.append({"page": idx, "start": start_offset, "end": end_offset})
    text = "\n\n".join(parts)
    if not text.strip():
        raise ValueError("No extractable text in this PDF (it may be a scan). Upload a text PDF or paste the copy.")
    return text, page_map


def render_pages(path, output_dir, prefix=""):
    """Render PDF pages as PNG images. Returns list of filenames.
    Gracefully returns [] if pypdfium2 is not installed."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return []
    try:
        doc = pdfium.PdfDocument(str(path))
        filenames = []
        out_dir = Path(output_dir)
        for idx, page in enumerate(doc, start=1):
            image = page.render(scale=2).to_pil()
            fname = f"{prefix}p{idx}.png" if prefix else f"page_{idx}.png"
            image.save(out_dir / fname)
            filenames.append(fname)
        return filenames
    except Exception:
        return []
