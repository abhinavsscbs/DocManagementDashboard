"""
EY PDF processor for International GAAP documents.
Extracts chapters and chunks content by bold headers.
"""

import re
import json
from statistics import median
import pandas as pd
import pdfplumber
from rapidfuzz import fuzz

from extractors.text_processing import simple_preprocess, normalize
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


# EY processing constants
EY_SKIP_PAGES = 15
EY_HEADER_FONT_THRESHOLD = 20
KEY_HEADER_PREFIXES = ("Question", "How we see it", "What you need to know", "Extract", "Example")
BOLD_KEYWORDS = ("bold", "black", "heavy", "semibold", "demi", "medium")
REGULAR_HEADER_FONTS = {"EYInterstate-Regular"}
MIN_SIZE_IF_REGULAR = 13.0


def extract_chapters_from_pdf_ey(pdf_path, max_pages=15):
    toc_headers = []
    start_headings = ["lists of chapters", "table of contents"]
    chapter_pattern = re.compile(r'^(\d{1,3}[A-Z]?)\s+(.+)', re.IGNORECASE)
    is_chapter_section = False

    def is_valid_header_line(line):
        return re.match(r'^\d{1,3}[A-Z]?', line)

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:max_pages]:
            text = page.extract_text()
            if not text:
                continue
            lines = text.split('\n')
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if not is_chapter_section and any(h in line.lower() for h in start_headings):
                    is_chapter_section = True
                    i += 1
                    continue
                if is_chapter_section:
                    match = chapter_pattern.match(line)
                    if match:
                        combined = line
                        i += 1
                        while i < len(lines):
                            next_line = lines[i].strip()
                            if chapter_pattern.match(next_line) or not is_valid_header_line(next_line):
                                break
                            combined += " " + next_line
                            i += 1
                        toc_headers.append(combined.strip())
                    else:
                        i += 1
                else:
                    i += 1
    return toc_headers


def detect_multiline_headers_ey(pdf_path, toc_headers, skip_pages=EY_SKIP_PAGES, header_font_threshold=EY_HEADER_FONT_THRESHOLD):
    found_map = {h: ("L Not Found", None) for h in toc_headers}
    normalized_tocs = [normalize(h) for h in toc_headers]

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages[skip_pages:], start=skip_pages + 1):
            header_chars = [c for c in page.chars if round(c.get("size", 0)) >= header_font_threshold]
            if not header_chars:
                continue
            header_chars.sort(key=lambda c: (round(c["top"]), c["x0"]))
            blocks, current_block, prev_top = [], [], None
            for c in header_chars:
                top = round(c["top"])
                if prev_top is None or abs(top - prev_top) <= 25:
                    current_block.append(c)
                else:
                    blocks.append(current_block)
                    current_block = [c]
                prev_top = top
            if current_block:
                blocks.append(current_block)

            grouped_headers = []
            for block in blocks:
                block.sort(key=lambda c: c["x0"])
                text = ''.join(c["text"] for c in block).strip()
                if text:
                    grouped_headers.append(text)

            header_candidates, temp = [], []
            for text in grouped_headers:
                if text: temp.append(text)
                else:
                    if temp:
                        header_candidates.append(" ".join(temp))
                        temp = []
            if temp: header_candidates.append(" ".join(temp))

            for idx, toc in enumerate(toc_headers):
                if found_map[toc][0] == " Found":
                    continue
                toc_norm = normalized_tocs[idx]
                toc_len = len(toc_norm)
                for candidate in header_candidates:
                    cand_norm = normalize(candidate)
                    if toc_len >= 30:
                        score = fuzz.ratio(cand_norm, toc_norm); threshold = 90
                    else:
                        p_score = fuzz.partial_ratio(cand_norm, toc_norm)
                        t_score = fuzz.token_sort_ratio(cand_norm, toc_norm)
                        score = (p_score + t_score) // 2; threshold = 85 if toc_len >= 20 else 80
                    if score >= threshold:
                        found_map[toc] = (" Found", page_num)
                        break
    return found_map


def is_keyword_header(line_text: str) -> bool:
    lt = line_text.strip()
    return any(lt.startswith(k) for k in KEY_HEADER_PREFIXES)


def is_bold_font(fontname: str) -> bool:
    return fontname and any(k in fontname.lower() for k in BOLD_KEYWORDS)


def group_words_into_lines(words, y_tol=2.0):
    if not words: return []
    words = sorted(words, key=lambda w: (round(w['top'], 1), w['x0']))
    lines, current = [], {'top': None, 'words': []}
    for w in words:
        if current['top'] is None:
            current['top'] = w['top']; current['words'] = [w]; continue
        if abs(w['top'] - current['top']) <= y_tol:
            current['words'].append(w)
        else:
            lines.append(current); current = {'top': w['top'], 'words': [w]}
    if current['words']: lines.append(current)
    out = []
    for line in lines:
        ws = line['words']
        text = " ".join(w['text'] for w in ws if w['text'].strip())
        if not text.strip(): continue
        bold_flags = [is_bold_font(w.get('fontname','') or '') for w in ws if w['text'].strip()]
        sizes = [float(w.get('size',0) or 0) for w in ws if w['text'].strip()]
        lefts = [float(w.get('x0',0) or 0) for w in ws if w['text'].strip()]
        out.append({
            "top": line['top'],
            "text": text.strip(),
            "bold_ratio": (sum(bold_flags)/len(bold_flags)) if bold_flags else 0.0,
            "avg_size": (sum(sizes)/len(sizes)) if sizes else 0.0,
            "left": min(lefts) if lefts else 0.0,
            "words": ws
        })
    return out


def merge_wrapped_headers(lines, indent_tolerance=15):
    merged, i, n = [], 0, len(lines)
    while i < n:
        ln = lines[i]
        if ln.get("is_header", False):
            acc_text, header_left, page = ln["text"], ln["left"], ln["page"]
            j = i + 1
            while j < n and lines[j].get("is_header", False) and abs(lines[j]["left"] - header_left) <= indent_tolerance:
                acc_text += " " + lines[j]["text"]; j += 1
            merged.append({"type":"header","text":acc_text.strip(),"page":page})
            i = j
        else:
            merged.append({"type":"body","text":ln["text"],"page":ln["page"]}); i += 1
    return merged


def chunk_span_by_bold_headers_ey(pdf_path, start_pg, end_pg, doc_name, chap_number, chapter_name,
                                  bold_ratio_threshold=0.6, size_boost=1.15, min_header_len=3):
    rows, items = [], []
    with pdfplumber.open(pdf_path) as pdf:
        start_pg = max(1, start_pg); end_pg = min(len(pdf.pages), end_pg)
        for pnum in range(start_pg, end_pg + 1):
            page = pdf.pages[pnum - 1]
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False, extra_attrs=["fontname","size"]) or []
            sizes = [float(w.get('size',0) or 0) for w in words if w.get('size')]
            page_median = median(sizes) if sizes else 0.0
            size_threshold = page_median * size_boost if page_median else 0.0

            lines = group_words_into_lines(words)
            tagged = []
            for ln in lines:
                text, avg_size, bold_ratio = ln["text"], ln["avg_size"], ln["bold_ratio"]
                spans_fonts = [w.get("fontname","") for w in ln["words"]]
                uses_regular_face = any(f in REGULAR_HEADER_FONTS for f in spans_fonts)
                reg_header = uses_regular_face and (avg_size >= MIN_SIZE_IF_REGULAR)
                is_header = (
                    is_keyword_header(text)
                    or (bold_ratio >= bold_ratio_threshold)
                    or (avg_size >= size_threshold)
                    or reg_header
                )
                tagged.append({"text":text,"left":ln["left"],"page":pnum,"is_header":is_header})
            items.extend(merge_wrapped_headers(tagged, indent_tolerance=15))

    current_header, current_header_page, buffer = None, None, []
    def flush():
        nonlocal current_header, current_header_page, buffer
        if current_header and len(current_header.strip()) >= min_header_len:
            para = " ".join(buffer).strip()
            if para:
                rows.append((
                    current_header.strip(),
                    current_header_page,
                    doc_name,
                    chap_number,
                    chapter_name,
                    para,
                    simple_preprocess(para)
                ))
        current_header, current_header_page, buffer = None, None, []

    for it in items:
        if it["type"] == "header":
            flush(); current_header, current_header_page = it["text"], it["page"]
        else:
            if current_header: buffer.append(it["text"])
    flush()
    return rows


def process_pdf_to_final_df_ey(pdf_path, doc_name=None):
    """
    Main entry point for EY PDF processing.

    Args:
        pdf_path: Path to the PDF file
        doc_name: Optional document name override

    Returns:
        pandas.DataFrame with columns: header, page, doc_name, chap_number,
                                       chapter_name, para, preprocessed, publisher
    """
    if doc_name is None:
        doc_name = get_doc_name("EY")

    toc_headers = extract_chapters_from_pdf_ey(pdf_path)
    header_map = detect_multiline_headers_ey(pdf_path, toc_headers, skip_pages=EY_SKIP_PAGES, header_font_threshold=EY_HEADER_FONT_THRESHOLD)
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
    spans = build_chapter_spans(toc_headers, header_map, total_pages)

    all_rows = []
    for sp in spans:
        chap_header = sp["chapter_header"]
        start_pg, end_pg = sp["start_page"], sp["end_page"]
        m = re.match(r"\s*(\d{1,3}[A-Z]?)\b", chap_header)
        chap_number = f"Chapter {m.group(1)}" if m else "Chapter ?"
        rows = chunk_span_by_bold_headers_ey(
            pdf_path, start_pg, end_pg, doc_name, chap_number, chap_header
        )
        all_rows.extend(rows)

    df = pd.DataFrame(
        all_rows,
        columns=["header","page","doc_name","chap_number","chapter_name","para","preprocessed"]
    )
    df["publisher"] = "EY"
    return df


def process_ey_json_to_df(json_path: str, doc_name: str = None) -> pd.DataFrame:
    """
    Convert an EY JSON export into the standard DataFrame schema.
    """
    if doc_name is None:
        doc_name = get_doc_name("EY")

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
    df["publisher"] = "EY"
    return df
