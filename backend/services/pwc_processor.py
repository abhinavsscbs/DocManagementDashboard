"""
PwC PDF processor for PwC Manual documents.
Extracts chapters and chunks content by font/color-based headers.
"""

import re
import json
import pandas as pd
import pdfplumber
import fitz  # PyMuPDF

from extractors.text_processing import simple_preprocess
from utils.config import get_doc_name
from services.helpers import build_chapter_spans


def _coerce_page(value) -> int:
    try:
        return int(float(value))
    except Exception:
        return 0


def _load_json_records(json_path: str) -> list:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("records", "rows", "data", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


# PwC processing constants
PWC_SKIP_PAGES = 10
PWC_HEADER_FONTS = {"LiberationSerif-BoldItalic", "LiberationSerif-Italic"}
PWC_HEADER_COLOR = {0, 14444800, 8421504, 2105636, 238, 255}
PWC_MIN_HEADER_SIZE = 21.0
PWC_JOIN_WRAPPED_HEADERS = True


def extract_chapters_from_pdf_pwc(pdf_path, max_pages=15):
    print(f"\n[PWC DEBUG] Starting ToC extraction from: {pdf_path}")
    print(f"[PWC DEBUG] Scanning first {max_pages} pages")

    start_headings = ["lists of chapters", "table of contents"]
    chapters = []; is_chapter_section = False; non_match_count = 0
    chapter_start_pattern = re.compile(r'^(\d+)[A-Z]?\s*[-\u2013]?\s+(.+)', re.IGNORECASE)
    multi_chapter_split_pattern = re.compile(
        r'(\d{1,2}[A-Z]?)\s*[-\u2013]\s*(.+?)(?=(\d{1,2}[A-Z]?\s*[-\u2013])|$)', re.IGNORECASE
    )

    with pdfplumber.open(pdf_path) as pdf:
        print(f"[PWC DEBUG] Total pages in PDF: {len(pdf.pages)}")

        for page_idx, page in enumerate(pdf.pages[:max_pages]):
            text = page.extract_text()
            if not text:
                print(f"[PWC DEBUG] Page {page_idx + 1}: No text extracted")
                continue

            print(f"[PWC DEBUG] Page {page_idx + 1}: Extracted {len(text)} characters")
            lines = text.split('\n'); i = 0

            while i < len(lines):
                line = lines[i].strip(); ll = line.lower()

                if not is_chapter_section and any(h in ll for h in start_headings):
                    is_chapter_section = True
                    print(f"[PWC DEBUG] Found ToC start on page {page_idx + 1}: '{line}'")
                    i += 1; continue

                if is_chapter_section:
                    if "appendix" in ll:
                        print(f"[PWC DEBUG] Skipping appendix line: '{line}'")
                        i += 1; continue

                    match = chapter_start_pattern.match(line)
                    if match:
                        buf = line; i += 1
                        while i < len(lines):
                            nxt = lines[i].strip(); nll = nxt.lower()
                            if chapter_start_pattern.match(nxt) or nxt == "" or "appendix" in nll: break
                            buf += " " + nxt; i += 1

                        for m in list(multi_chapter_split_pattern.finditer(buf)):
                            raw = buf[m.start():m.end()].strip()
                            chapters.append(raw)
                            print(f"[PWC DEBUG] Found chapter: '{raw}'")
                        non_match_count = 0
                    else:
                        non_match_count += 1
                        if non_match_count >= 3:
                            print(f"[PWC DEBUG] Stopping ToC extraction after {non_match_count} non-matches")
                            print(f"[PWC DEBUG] Total chapters found: {len(chapters)}")
                            return chapters
                        i += 1
                else:
                    i += 1

    print(f"[PWC DEBUG] ToC extraction complete. Total chapters: {len(chapters)}")
    return chapters


def loose_header_pattern(header: str) -> str:
    escaped = re.escape(header.strip())
    return re.sub(r'\\ ', r'\\s+', escaped)


def detect_multiline_headers_pwc(pdf_path, toc_headers, skip_pages=PWC_SKIP_PAGES):
    print(f"\n[PWC DEBUG] Starting header detection")
    print(f"[PWC DEBUG] Skipping first {skip_pages} pages")
    print(f"[PWC DEBUG] Looking for {len(toc_headers)} headers")

    header_map = {h: ("L Not Found", None) for h in toc_headers}

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        print(f"[PWC DEBUG] Scanning pages {skip_pages + 1} to {total_pages}")
        page_texts = [(page.extract_text() or "") for page in pdf.pages[skip_pages:]]

    for h in toc_headers:
        pat = loose_header_pattern(h)
        print(f"[PWC DEBUG] Searching for: '{h}' with pattern")
        found = None

        for idx, text in enumerate(page_texts):
            if re.search(pat, text, re.IGNORECASE):
                found = skip_pages + idx + 1
                print(f"[PWC DEBUG]    Found on page {found}")
                break

        if found:
            header_map[h] = (" Found", found)
        else:
            print(f"[PWC DEBUG]   L Not found")

    found_count = sum(1 for v in header_map.values() if v[0] == " Found")
    print(f"[PWC DEBUG] Header detection complete: {found_count}/{len(toc_headers)} found")
    return header_map


def is_pwc_header_span(span) -> bool:
    font_name = span.get("font"); size = float(span.get("size", 0.0) or 0.0); color = span.get("color")
    return (font_name in PWC_HEADER_FONTS) and (size > PWC_MIN_HEADER_SIZE) and (color in PWC_HEADER_COLOR)


def chunk_span_by_pwc_headers(pdf_path, start_pg, end_pg, doc_name, chap_number, chapter_name):
    print(f"\n[PWC DEBUG] Chunking chapter '{chap_number}' (pages {start_pg}-{end_pg})")

    rows = []
    doc = fitz.open(pdf_path)
    start_pg = max(1, start_pg); end_pg = min(len(doc), end_pg)
    current_header = None; current_header_page = None; current_paragraph = ""; in_header = False

    header_count = 0

    for pnum in range(start_pg, end_pg + 1):
        page = doc[pnum - 1]
        blocks = page.get_text("dict")["blocks"]

        print(f"[PWC DEBUG]   Page {pnum}: {len(blocks)} blocks")

        for b in blocks:
            if b.get("type") != 0: continue
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    text = (span.get("text") or "").strip()
                    if not text: continue

                    if is_pwc_header_span(span):
                        header_count += 1
                        print(f"[PWC DEBUG]   Found header #{header_count} on page {pnum}: '{text[:50]}...'")

                        if in_header and PWC_JOIN_WRAPPED_HEADERS and current_header:
                            current_header += " " + text
                        else:
                            if current_header and current_paragraph.strip():
                                para = current_paragraph.strip()
                                rows.append((
                                    current_header.strip(),
                                    current_header_page,
                                    doc_name,
                                    chap_number,
                                    chapter_name,
                                    para,
                                    simple_preprocess(para)
                                ))
                                current_paragraph = ""
                            current_header = text; current_header_page = pnum; in_header = True
                    else:
                        if in_header: in_header = False
                        current_paragraph += text + " "

    if current_header and current_paragraph.strip():
        para = current_paragraph.strip()
        rows.append((
            current_header.strip(),
            current_header_page or end_pg,
            doc_name,
            chap_number,
            chapter_name,
            para,
            simple_preprocess(para)
        ))

    doc.close()
    print(f"[PWC DEBUG]   Chapter chunking complete: {len(rows)} chunks, {header_count} headers found")
    return rows


def process_pdf_to_final_df_pwc(pdf_path, doc_name=None):
    """
    Main entry point for PwC PDF processing.

    Args:
        pdf_path: Path to the PDF file
        doc_name: Optional document name override

    Returns:
        pandas.DataFrame with columns: header, page, doc_name, chap_number,
                                       chapter_name, para, preprocessed, publisher
    """
    if doc_name is None:
        doc_name = get_doc_name("PwC")

    print(f"\n{'='*60}")
    print(f"[PWC DEBUG] STARTING PWC PROCESSING")
    print(f"[PWC DEBUG] File: {pdf_path}")
    print(f"{'='*60}")

    # Step 1: Extract ToC
    toc_headers = extract_chapters_from_pdf_pwc(pdf_path, max_pages=PWC_SKIP_PAGES)
    if not toc_headers:
        print("[PWC DEBUG] � WARNING: No ToC headers found!")

    # Step 2: Detect headers
    header_map = detect_multiline_headers_pwc(pdf_path, toc_headers, skip_pages=PWC_SKIP_PAGES)

    # Step 3: Build spans
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)

    print(f"\n[PWC DEBUG] Building chapter spans...")
    spans = build_chapter_spans(toc_headers, header_map, total_pages)
    print(f"[PWC DEBUG] Created {len(spans)} chapter spans")

    for i, sp in enumerate(spans):
        print(f"[PWC DEBUG]   Span {i+1}: '{sp['chapter_header'][:50]}...' (pages {sp['start_page']}-{sp['end_page']})")

    # Step 4: Chunk each span
    all_rows = []
    for sp in spans:
        chap_header, start_pg, end_pg = sp["chapter_header"], sp["start_page"], sp["end_page"]
        m = re.match(r"\s*(\d{1,3}[A-Z]?)\b", chap_header)
        chap_number = f"Chapter {m.group(1)}" if m else "Chapter ?"

        rows = chunk_span_by_pwc_headers(pdf_path, start_pg, end_pg, doc_name, chap_number, chap_header)
        all_rows.extend(rows)

    print(f"\n[PWC DEBUG] Total rows extracted: {len(all_rows)}")

    df = pd.DataFrame(
        all_rows,
        columns=["header","page","doc_name","chap_number","chapter_name","para","preprocessed"]
    )
    df["publisher"] = "PwC"

    print(f"[PWC DEBUG] Final DataFrame shape: {df.shape}")
    print(f"{'='*60}\n")

    return df


def process_pwc_json_to_df(json_path: str, doc_name: str = None) -> pd.DataFrame:
    """
    Convert a PwC JSON export into the standard DataFrame schema.
    """
    if doc_name is None:
        doc_name = get_doc_name("PwC")

    records = []
    for r in _load_json_records(json_path):
        if not isinstance(r, dict):
            continue
        para = (r.get("para") or "").strip()
        if not para:
            continue
        preprocessed = (r.get("preprocessed") or "").strip() or simple_preprocess(para)
        records.append({
            "header": (r.get("header") or "").strip(),
            "page": _coerce_page(r.get("page")),
            "doc_name": (r.get("doc_name") or doc_name),
            "chap_number": (r.get("chap_number") or "Chapter ?"),
            "chapter_name": (r.get("chapter_name") or ""),
            "para": para,
            "preprocessed": preprocessed,
        })

    df = pd.DataFrame.from_records(
        records,
        columns=["header", "page", "doc_name", "chap_number", "chapter_name", "para", "preprocessed"]
    )
    df["publisher"] = "PwC"
    return df


def debug_pwc_fonts_detailed(pdf_path, sample_pages=20):
    """Inspect actual fonts, colors, and sizes in the PDF"""
    print("\n" + "="*60)
    print("[PWC FONT DEBUG] Analyzing PDF structure...")
    print("="*60)

    doc = fitz.open(pdf_path)

    # Collect all unique combinations
    font_size_combos = set()

    for pnum in range(min(sample_pages, len(doc))):
        page = doc[pnum]
        blocks = page.get_text("dict")["blocks"]

        for b in blocks:
            if b.get("type") != 0: continue
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    text = (span.get("text") or "").strip()
                    if not text or len(text) < 10:  # Skip short text
                        continue

                    font = span.get("font")
                    size = round(span.get("size", 0), 1)
                    color = span.get("color")

                    font_size_combos.add((font, size, color, text[:50]))

    doc.close()

    # Group and display
    print(f"\nFound {len(font_size_combos)} unique font/size/color combinations:\n")

    for font, size, color, sample in sorted(font_size_combos, key=lambda x: (-x[1], x[0])):
        print(f"Font: {font:40s} | Size: {size:5.1f} | Color: {color} | Sample: '{sample}'")

    print("\n" + "="*60)

    # Suggest what to use
    sizes = [s for _, s, _, _ in font_size_combos]
    if sizes:
        print(f"\nSize range: {min(sizes):.1f} - {max(sizes):.1f}")
        print(f"Suggested header size threshold: {sorted(sizes, reverse=True)[min(5, len(sizes)-1)]:.1f}")

    fonts = set(f for f, _, _, _ in font_size_combos)
    print(f"\nUnique fonts found: {fonts}")

    colors = set(c for _, _, c, _ in font_size_combos)
    print(f"Unique colors found: {colors}")

    print("="*60 + "\n")
