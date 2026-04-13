"""
pdf_processor.py
Extracts text, tables, and images from a PDF using PyMuPDF.
Returns structured chunks ready for AI processing.

Improvements over v1:
  - Uses page.find_tables() for accurate table detection (PyMuPDF 1.23+)
  - Falls back to heuristic detection for older builds
  - Stores table Markdown AND raw cell data in chunk
  - Stores images as base64 per chunk (for Groq vision API)
"""
import fitz  # PyMuPDF
import base64
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from io import BytesIO
from PIL import Image


@dataclass
class TableData:
    markdown: str       # formatted markdown table string
    page_num: int
    caption: str = ""   # optional: text found near the table


@dataclass
class Chunk:
    index: int
    page_range: str          # e.g. "1-3"
    text: str                # combined text (with table/image descriptions inline)
    has_image: bool = False
    has_table: bool = False
    image_descriptions: List[str] = field(default_factory=list)  # filled by AI later
    tables: List[TableData]  = field(default_factory=list)       # structured tables


@dataclass
class ExtractedPaper:
    title: str
    full_text: str
    chunks: List[Chunk]
    num_pages: int
    has_images: bool
    has_tables: bool


MAX_CHUNK_CHARS = 4000   # ~1000 tokens, safe for Groq/Gemini
OVERLAP_CHARS   = 400    # overlap between consecutive chunks


# ── Table extraction ─────────────────────────────────────────────────────────

def _cells_to_markdown(cells: List[List[str]]) -> str:
    """Convert a 2-D list of cell strings into a Markdown table."""
    if not cells:
        return ""
    max_cols = max(len(row) for row in cells)
    # Pad rows to equal width
    rows = [row + [""] * (max_cols - len(row)) for row in cells]

    header = rows[0]
    md = "| " + " | ".join(header) + " |\n"
    md += "| " + " | ".join(["---"] * max_cols) + " |\n"
    for row in rows[1:]:
        md += "| " + " | ".join(row) + " |\n"
    return md


def _extract_tables_native(page) -> List[TableData]:
    """
    Use PyMuPDF's built-in find_tables() method (available in 1.23+).
    Returns a list of TableData objects.
    """
    tables: List[TableData] = []
    try:
        tab_finder = page.find_tables()
        for t in tab_finder.tables:
            try:
                rows = t.extract()         # List[List[str | None]]
                # Coerce None → ""
                cleaned = [
                    [str(c).strip() if c is not None else "" for c in row]
                    for row in rows
                ]
                if len(cleaned) < 2:       # need header + at least one data row
                    continue
                md = _cells_to_markdown(cleaned)
                tables.append(TableData(markdown=md, page_num=page.number + 1))
            except Exception:
                pass
    except AttributeError:
        pass  # PyMuPDF version doesn't have find_tables
    return tables


def _is_table_block_heuristic(block) -> bool:
    """Fallback heuristic: a text block is table-like if it has many tab/pipe chars."""
    text = block.get("text", "") if isinstance(block, dict) else ""
    lines = text.splitlines()
    if len(lines) < 2:
        return False
    tabbed = sum(1 for ln in lines if "\t" in ln or "  " in ln)
    return tabbed / max(len(lines), 1) > 0.5


def _block_to_markdown_table(text: str) -> str:
    """Convert a tab-/space-separated block to a Markdown table (heuristic path)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return text
    rows = [re.split(r"\s{2,}|\t", line) for line in lines]
    return _cells_to_markdown(rows)


# ── Image extraction ──────────────────────────────────────────────────────────

def _extract_images_from_page(page, doc) -> List[str]:
    """Extract images from a page; return them as base64 PNG strings."""
    images_b64: List[str] = []
    for img_info in page.get_images(full=True):
        xref = img_info[0]
        try:
            base_image = doc.extract_image(xref)
            img_bytes  = base_image["image"]
            img = Image.open(BytesIO(img_bytes)).convert("RGB")
            # Resize to keep token usage manageable
            if img.width > 1024 or img.height > 1024:
                img.thumbnail((1024, 1024), Image.LANCZOS)
            # Skip tiny images (likely icons/logos)
            if img.width < 50 or img.height < 50:
                continue
            buf = BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            images_b64.append(b64)
        except Exception:
            pass
    return images_b64


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_paper(pdf_bytes: bytes) -> ExtractedPaper:
    """
    Accept raw PDF bytes; return ExtractedPaper with text chunks,
    structured tables, and base64 images per chunk.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    num_pages = doc.page_count

    page_data: List[dict] = []   # {page_num, text, has_table, has_image, images_b64, tables}

    for page_num in range(num_pages):
        page   = doc[page_num]
        blocks = page.get_text("dict")["blocks"]

        page_text_parts: List[str] = []
        has_table = False
        has_image = False

        # ── Native table extraction (preferred) ──────────────────────────
        native_tables = _extract_tables_native(page)
        if native_tables:
            has_table = True
            for tbl in native_tables:
                page_text_parts.append(f"\n[TABLE - Page {tbl.page_num}]\n{tbl.markdown}\n")

        # ── Text block extraction ────────────────────────────────────────
        for block in blocks:
            btype = block.get("type", -1)
            if btype == 0:  # text block
                raw = "\n".join(
                    span["text"]
                    for line in block.get("lines", [])
                    for span in line.get("spans", [])
                )
                if not native_tables and _is_table_block_heuristic(block):
                    has_table = True
                    page_text_parts.append(
                        f"\n[TABLE]\n{_block_to_markdown_table(raw)}\n"
                    )
                else:
                    page_text_parts.append(raw)
            elif btype == 1:  # image block placeholder
                has_image = True

        # ── Image extraction ─────────────────────────────────────────────
        images_b64 = _extract_images_from_page(page, doc)
        if images_b64:
            has_image = True

        page_text = "\n".join(page_text_parts).strip()
        page_data.append({
            "page_num"  : page_num + 1,
            "text"      : page_text,
            "has_table" : has_table,
            "has_image" : has_image,
            "images_b64": images_b64,
            "tables"    : native_tables,
        })

    doc.close()

    # ── Full text & title ─────────────────────────────────────────────────
    full_text = "\n\n".join(p["text"] for p in page_data)
    title = "Untitled Paper"
    for line in page_data[0]["text"].splitlines():
        line = line.strip()
        if len(line) > 10:
            title = line[:200]
            break

    # ── Chunking ──────────────────────────────────────────────────────────
    chunks: List[Chunk] = []
    current_text  = ""
    current_pages: List[int] = []
    has_img_acc   = False
    has_tbl_acc   = False
    images_acc: List[str]     = []
    tables_acc: List[TableData] = []
    chunk_idx     = 0

    def _flush_chunk():
        nonlocal current_text, current_pages, has_img_acc, has_tbl_acc
        nonlocal images_acc, tables_acc, chunk_idx
        if not current_text.strip():
            return
        page_range = (
            str(current_pages[0])
            if len(set(current_pages)) == 1
            else f"{current_pages[0]}-{current_pages[-1]}"
        )
        chunk = Chunk(
            index      = chunk_idx,
            page_range = page_range,
            text       = current_text.strip(),
            has_image  = has_img_acc,
            has_table  = has_tbl_acc,
            tables     = tables_acc[:],
        )
        # Store raw b64 images for AI vision calls
        chunk._images_b64 = images_acc[:]   # type: ignore[attr-defined]
        chunks.append(chunk)
        chunk_idx += 1
        # Overlap
        current_text  = current_text[-OVERLAP_CHARS:]
        current_pages = current_pages[-1:]
        has_img_acc   = False
        has_tbl_acc   = False
        images_acc    = []
        tables_acc    = []

    for pdata in page_data:
        page_section = f"\n[Page {pdata['page_num']}]\n{pdata['text']}"
        current_text += page_section
        current_pages.append(pdata["page_num"])
        if pdata["has_image"]:
            has_img_acc = True
        if pdata["has_table"]:
            has_tbl_acc = True
        images_acc.extend(pdata["images_b64"])
        tables_acc.extend(pdata["tables"])

        while len(current_text) > MAX_CHUNK_CHARS:
            split_at = current_text.rfind("\n\n", 0, MAX_CHUNK_CHARS)
            if split_at <= OVERLAP_CHARS:
                split_at = current_text.rfind(". ", 0, MAX_CHUNK_CHARS)
            if split_at <= OVERLAP_CHARS:
                split_at = MAX_CHUNK_CHARS
            chunk_text   = current_text[:split_at].strip()
            saved        = current_text
            current_text = chunk_text
            _flush_chunk()
            current_text  = current_text + saved[split_at:]
            current_pages = [pdata["page_num"]] + current_pages

    _flush_chunk()

    return ExtractedPaper(
        title      = title,
        full_text  = full_text,
        chunks     = chunks,
        num_pages  = num_pages,
        has_images = any(p["has_image"] for p in page_data),
        has_tables = any(p["has_table"] for p in page_data),
    )
