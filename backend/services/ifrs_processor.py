"""
IFRS PDF processor using spatial extraction and EnhancedPDFExtractor.
"""

import os
import re
import json
import tempfile
import zipfile
import hashlib
from statistics import median
from typing import List, Tuple, Dict, Any, Optional
from dataclasses import dataclass, asdict
import pandas as pd
import fitz  # PyMuPDF
from extractors.text_processing import simple_preprocess, normalize
from utils.config import get_doc_name, get_faiss_dir

# ======================== Helper Functions ========================
def _save_uploaded_to_tmp(uploaded_file, suffix=".pdf") -> str:
    """
    Save an uploaded file to a temporary location.

    Args:
        uploaded_file: File object with a read() method
        suffix: File extension (default: ".pdf")

    Returns:
        str: Path to the temporary file
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.read())
        return tmp.name

# Get the BOLD_FLAG constant
BOLD_FLAG = getattr(fitz, "TEXT_FONT_BOLD", 16)

# ===================== UPDATED IFRS EXTRACTION (STRICTER LOGIC) =====================

# ---------- Enhanced ID Validation Patterns ----------
_STRICT_ID_RE = re.compile(
    r"""^(
        \d+                              # 1, 11, 123
        |[A-Za-z]{1,6}\d+[A-Za-z]{0,6}   # IE1, BC11, BC11A, IN1
        |\d+[A-Za-z]{1,6}                # 11B, 2BC
    )$""",
    re.VERBOSE,
)

_EXCLUDE_ID_RES = [
    re.compile(r"^CU\d+$", re.I),                                  # CU20
    re.compile(r"^(USD|SAR|EUR|GBP|AED)\s?\d+(?:[\.,]\d+)?$", re.I),
    re.compile(r"^[\$€£]\s?\d+(?:[\.,]\d+)?$"),
    re.compile(r"^B\d{3,}$", re.I),                               # B798 footers
    # NEW: Exclude months/days
    re.compile(r"^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)$", re.I),
    re.compile(r"^(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)$", re.I),
    re.compile(r"^(MON|TUE|WED|THU|FRI|SAT|SUN)$", re.I),
    # NEW: Exclude IFRS example years
    re.compile(r"^20X\d$", re.I),  # 20X1, 20X2, etc.
]

_PREFERRED_PREFIX_RE = re.compile(r"^(IE|BC|AG|IFRS|IAS)\d", re.I)
_TRIM_PUNCT_RE = re.compile(r"^[\(\[\{]+|[)\]\}\.\,:;]+$")

def _normalize_id_candidate(tok: Optional[str]) -> Optional[str]:
    """Strip outer parens/punct and spaces: '(IE1).' -> 'IE1'."""
    if not tok:
        return None
    t = tok.strip()
    t = _TRIM_PUNCT_RE.sub("", t)
    t = _TRIM_PUNCT_RE.sub("", t)  # twice to handle nested
    t = re.sub(r"\s+", "", t)
    return t.strip() or None

def _is_valid_para_id_strict(pid: Optional[str]) -> bool:
    """Strict validation: shape + not blacklisted + preferred prefix for letters-first."""
    if not pid:
        return False
    pid = pid.strip()
    if not _STRICT_ID_RE.match(pid):
        return False
    for bad in _EXCLUDE_ID_RES:
        if bad.match(pid):
            return False
    # Letters-first must have preferred prefix (IE, BC, AG, etc.)
    if pid[0].isalpha() and not _PREFERRED_PREFIX_RE.match(pid):
        return False
    return True

# ---------- Enhanced Horizontal Rule Detection ----------
def _collect_horizontal_rules_strict(page, max_height=3.0, min_width_ratio=0.4):
    """
    Collect horizontal lines from both:
      • Thin rectangles (height<=max_height, width>=min_width_ratio*page_width)
      • Path-based lines ('l' items in drawings)
    Returns list of [x0,y0,x1,y1].
    """
    W = float(page.rect.width)
    rules = []

    def add_rule_box(x0, y0, x1, y1):
        if x1 <= x0:
            return
        width = x1 - x0
        if width >= min_width_ratio * W:
            rules.append([round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)])

    try:
        for d in page.get_drawings():
            # Rectangle-based lines
            rect = d.get("rect")
            if isinstance(rect, fitz.Rect):
                if rect.height <= max_height and rect.width >= min_width_ratio * W:
                    add_rule_box(rect.x0, rect.y0, rect.x1, rect.y1)
                    continue
            
            # Path-based lines ('l' items)
            for it in d.get("items", []):
                if not it or len(it) < 2:
                    continue
                if it[0] != "l":  # line item
                    continue
                pts = it[1]
                if not isinstance(pts, (list, tuple)) or len(pts) != 2:
                    continue
                (x0, y0), (x1, y1) = pts
                if abs(y1 - y0) <= 0.75:  # nearly-horizontal
                    y_top = min(y0, y1)
                    y_bot = max(y0, y1)
                    add_rule_box(min(x0, x1), y_top, max(x0, x1), max(y_bot, y_top + 1.0))
    except Exception:
        pass

    # Deduplicate nearby lines
    rules.sort(key=lambda b: (round(b[1], 1), round(b[0], 1)))
    dedup = []
    for box in rules:
        if not dedup:
            dedup.append(box)
            continue
        x0, y0, x1, y1 = box
        px0, py0, px1, py1 = dedup[-1]
        if abs(y0 - py0) <= 1.0 and min(x1, px1) - max(x0, px0) > 0.5 * min(x1 - x0, px1 - px0):
            # Merge overlapping rules
            dedup[-1] = [min(x0, px0), min(y0, py0), max(x1, px1), max(y1, py1)]
        else:
            dedup.append(box)
    return dedup

def _pair_rules_with_blocks_strict(blocks, rule_boxes,
                                   max_vertical_gap=30.0,
                                   min_horiz_overlap_ratio=0.5,
                                   min_rule_over_text_width_ratio=0.6):
    """
    Pair horizontal rules with text blocks ABOVE them:
      • block_bottom <= rule_top
      • vertical gap <= max_vertical_gap
      • horizontal overlap >= min_horiz_overlap_ratio
      • rule width >= min_rule_over_text_width_ratio of block width
    Returns: (header_block_ids, kept_rules)
    """
    header_ids = set()
    kept_rules = []

    candidates = []
    for i, b in enumerate(blocks):
        if "lines" not in b:
            continue
        bbox = b.get("bbox")
        if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            continue
        # Must have non-empty text
        txt = ""
        for ln in b.get("lines", []):
            for sp in ln.get("spans", []):
                t = sp.get("text", "")
                if t:
                    txt += t
        if not txt.strip():
            continue
        candidates.append((i, bbox))

    for r in rule_boxes:
        rx0, ry0, rx1, ry1 = r
        rW = rx1 - rx0
        best = None
        best_gap = 1e9
        
        for idx, bb in candidates:
            x0, y0, x1, y1 = bb
            if y1 > ry0:  # block must be above rule
                continue
            gap = ry0 - y1
            if gap > max_vertical_gap:
                continue
            
            block_w = max(x1 - x0, 1.0)
            overlap = min(rx1, x1) - max(rx0, x0)
            if overlap <= 0:
                continue
            
            overlap_ratio = overlap / block_w
            if overlap_ratio < min_horiz_overlap_ratio:
                continue
            if (rW / block_w) < min_rule_over_text_width_ratio:
                continue
            
            if gap < best_gap:
                best_gap = gap
                best = idx
        
        if best is not None:
            header_ids.add(best)
            kept_rules.append(r)

    return header_ids, kept_rules

# ---------- Enhanced ID Token Attachment (Left-to-Right) ----------
def _first_id_like_token_leftright(line):
    """Scan tokens left→right; return first valid ID-like token & bbox."""
    if not line["tokens"]:
        return None, None
    toks = sorted(line["tokens"], key=lambda z: z["x0"])
    for w in toks:
        cand = _normalize_id_candidate(w["text"])
        if not cand:
            continue
        if _is_valid_para_id_strict(cand):
            bbox = [round(w["x0"], 2), round(w["y0"], 2), round(w["x1"], 2), round(w["y1"], 2)]
            return cand, bbox
    return None, None

def _attach_id_token_to_block_strict(block_bbox, lines, y_tol=14.0):
    """
    Find nearest line to block top and return first valid ID token on it.
    Checks small neighborhood of lines.
    """
    if not block_bbox or not lines:
        return None, None

    top_y = block_bbox[1]
    lo, hi = 0, len(lines) - 1
    best_i, best_d = None, 1e9
    while lo <= hi:
        mid = (lo + hi) // 2
        d = abs(lines[mid]["y_mid"] - top_y)
        if d < best_d:
            best_d, best_i = d, mid
        if lines[mid]["y_mid"] < top_y:
            lo = mid + 1
        else:
            hi = mid - 1
    if best_i is None or best_d > y_tol:
        return None, None

    start = max(0, best_i - 2)
    end = min(len(lines), best_i + 3)
    for j in range(start, end):
        tok, bb = _first_id_like_token_leftright(lines[j])
        if tok:
            return tok, bb
    return None, None

# ---------- Updated Object Extraction Function ----------
def extract_ifrs_objects_spatial_v2(doc: fitz.Document) -> List[Dict]:
    """
    UPDATED: Extract objects with STRICT header detection (underline pairing)
    and enhanced ID validation.
    """
    all_objects = []

    for page_num, page in enumerate(doc, start=1):
        tdict = page.get_text("dict")
        blocks = tdict.get("blocks", [])
        words = page.get_text("words")
        lines = _build_lines(words)
        
        # STRICT underline header detection
        rule_boxes = _collect_horizontal_rules_strict(page, max_height=3.0, min_width_ratio=0.4)
        header_block_ids, kept_rules = _pair_rules_with_blocks_strict(
            blocks, rule_boxes,
            max_vertical_gap=30.0,
            min_horiz_overlap_ratio=0.5,
            min_rule_over_text_width_ratio=0.6
        )

        for b_idx, b in enumerate(blocks):
            if "lines" not in b:
                continue

            spans_sizes = []
            text_parts = []
            for ln in b.get("lines", []):
                for s in ln.get("spans", []):
                    t = s.get("text", "")
                    if t:
                        text_parts.append(t)
                    if "size" in s:
                        spans_sizes.append(s["size"])

            block_text = " ".join(text_parts).strip()
            if not block_text:
                continue

            avg_font = round(sum(spans_sizes) / len(spans_sizes), 1) if spans_sizes else 0.0
            bbox = b.get("bbox")
            bbox_list = [round(x, 2) for x in bbox] if isinstance(bbox, (list, tuple)) else _rect_to_list(bbox)
            is_header_by_rule = (b_idx in header_block_ids)
            
            # STRICT: heading only if paired with underline
            otype = _guess_type(block_text, avg_font, is_header_by_rule)

            # Attach ID token with strict validation
            para_number, number_bbox = _attach_id_token_to_block_strict(
                bbox_list, lines, y_tol=14.0
            )

            all_objects.append({
                "type": otype,
                "page": page_num,
                "bbox": bbox_list,
                "attrs": {
                    "fontsize": avg_font,
                    "header_marked_by_rule": bool(is_header_by_rule),
                    "para_number": para_number,
                    "para_number_bbox": number_bbox,
                },
                "text": block_text,
                "values": None
            })

        # Record only kept rules (paired with headers)
        for r in kept_rules:
            all_objects.append({
                "type": "header_rule",
                "page": page_num,
                "bbox": r,
                "attrs": {},
                "text": None,
                "values": None
            })

    return all_objects

# ---------- Page Noise Removal Patterns ----------
_PAGE_HEADER_LINE_RE = re.compile(r"^\s*(IFRS|IAS)\s*\d+(\s*[-–].*)?$", re.I)
_FOOTER_LINE_RE = re.compile(r"^(?:[A-Z]?\d{2,}\s+)?©\s*IFRS\s+Foundation\s*$", re.I)

def _strip_page_noise(txt: str) -> str:
    """Remove 'IFRS 15' headers and '© IFRS Foundation' footers."""
    if not txt:
        return txt
    lines = txt.splitlines()
    cleaned = []
    for i, line in enumerate(lines):
        if i == 0 and _PAGE_HEADER_LINE_RE.match(line.strip()):
            continue  # Drop first line if page header
        if _FOOTER_LINE_RE.match(line.strip()):
            continue  # Drop footer lines
        cleaned.append(line)
    return "\n".join(cleaned)

def _text_starts_with_id(text: str, pid: str) -> bool:
    """True if text starts with pid (optionally followed by space/punct/newline)."""
    if not text or not pid:
        return False
    pattern = re.compile(rf"^\s*{re.escape(pid)}(?:\b|[\s\)\].,:;-])", re.IGNORECASE)
    return bool(pattern.match(text))

def _strip_leading_id_from_text(text: str, pid: str) -> str:
    """Remove duplicated leading pid from paragraph body: 'IE1 ' -> ''."""
    if not text or not pid:
        return text or ""
    t = text.lstrip()
    pat = re.compile(rf"^(?:{re.escape(pid)})\s*([)\].:,-])?", re.IGNORECASE)
    m = pat.match(t)
    if m:
        t = t[m.end():].lstrip()
    return t if t else text

# ---------- Updated Section Building Function ----------
def build_sections_mainparas_v2(objects: List[Dict]) -> Dict:
    """
    FIXED: Consistent page number handling (always use 'pages' list).
    """
    stream = sorted(
        (o for o in objects if o.get("type") in ("heading", "paragraph", "list_item")),
        key=lambda o: (int(o.get("page", 0)), _y0_of(o))
    )

    sections = []
    current_section = None
    current_para = None
    pending_intro = []

    def start_section(hobj):
        nonlocal current_section, current_para, pending_intro
        attrs = hobj.get("attrs", {}) or {}
        header = {
            "text": _normalize_preserve_lines(hobj.get("text", "") or ""),
            "page": hobj.get("page"),
            "bbox": hobj.get("bbox"),
            "fontsize": attrs.get("fontsize"),
        }
        current_section = {
            "header": header,
            "start_page": hobj.get("page"),
            "end_page": hobj.get("page"),
            "paragraphs": []
        }
        sections.append(current_section)
        current_para = None
        pending_intro = []

    def flush_current_para():
        nonlocal current_para
        if current_para and current_section:
            current_para["text"] = _normalize_preserve_lines(current_para["text"])
            current_para["pages"] = sorted(set(current_para["pages"]))
            current_section["paragraphs"].append(current_para)
        current_para = None

    def flush_intro():
        nonlocal pending_intro, current_section
        if not pending_intro or not current_section:
            return
        joined = _normalize_preserve_lines("\n".join(ch["text"] for ch in pending_intro if ch.get("text")))
        # FIXED: Use 'pages' (list) for consistency
        intro_pages = sorted(set(int(ch["page"]) for ch in pending_intro))
        if joined:
            current_section["paragraphs"].append({
                "id": None, 
                "pages": intro_pages,  # ← FIXED: was "page" 
                "text": joined
            })
        pending_intro = []

    for obj in stream:
        page = obj.get("page")
        if current_section:
            current_section["end_page"] = max(current_section["end_page"], page)

        # Normalize and strip page noise
        raw_txt = obj.get("text", "") or ""
        txt = _normalize_preserve_lines(raw_txt)
        txt = _strip_page_noise(txt)

        if _is_header(obj):
            flush_current_para()
            flush_intro()
            start_section(obj)
            continue

        attrs = obj.get("attrs", {}) or {}

        if current_section is None:
            start_section({
                "type": "heading",
                "text": "Document Start",
                "page": page,
                "bbox": obj.get("bbox"),
                "attrs": {"fontsize": None}
            })

        # BULLET GUARD
        if _BULLET_RE.match(txt):
            if current_para is not None:
                joiner = "\n" if (current_para["text"] and txt) else ""
                current_para["text"] = (current_para["text"] + joiner + txt).strip()
                # FIXED: Ensure page is added to pages list
                if page not in current_para["pages"]:
                    current_para["pages"].append(page)
            else:
                if current_section["paragraphs"]:
                    current_para = current_section["paragraphs"][-1]
                    joiner = "\n" if (current_para["text"] and txt) else ""
                    current_para["text"] = (current_para["text"] + joiner + txt).strip()
                    if page not in current_para["pages"]:
                        current_para["pages"].append(page)
                else:
                    pending_intro.append({"page": page, "text": txt})
            continue

        # Check for paragraph ID
        raw_pid = attrs.get("para_number")
        pid = _normalize_id_candidate(raw_pid) if isinstance(raw_pid, str) else None
        pid = pid if _is_valid_para_id_strict(pid) else None

        starts_new_para = False
        if pid is not None:
            starts_new_para = _text_starts_with_id(txt, pid)

        if starts_new_para:
            flush_current_para()
            flush_intro()
            body = _strip_leading_id_from_text(txt, pid)
            current_para = {
                "id": pid,
                "text": body,
                "pages": [page],
                "bboxes": [obj.get("bbox")] if obj.get("bbox") else [],
                "para_number_bbox": attrs.get("para_number_bbox")
            }
            continue

        # Append to current para or accumulate intro
        if current_para is not None:
            joiner = "\n" if (current_para["text"] and txt) else ""
            current_para["text"] = (current_para["text"] + joiner + txt).strip()
            if page not in current_para["pages"]:
                current_para["pages"].append(page)
            if obj.get("bbox"):
                current_para["bboxes"].append(obj["bbox"])
        else:
            pending_intro.append({"page": page, "text": txt})

    flush_current_para()
    flush_intro()

    return {"sections": sections}

# ---------- Updated Pipeline Function ----------
def process_ifrs_pdf_spatial_v2(pdf_path: str, label: str) -> pd.DataFrame:
    """
    FIXED: Robust page number extraction.
    """
    doc = fitz.open(pdf_path)
    standard_name = os.path.splitext(os.path.basename(pdf_path))[0]
    
    try:
        objects = extract_ifrs_objects_spatial_v2(doc)
        sections_data = build_sections_mainparas_v2(objects)
        sections = sections_data.get("sections", [])
        sections = consolidate_sameid_paragraphs(sections)
        
        records = []
        for section in sections:
            header_text = section.get("header", {}).get("text", "")
            
            for para in section.get("paragraphs", []):
                para_id = para.get("id")
                para_text = (para.get("text") or "").strip()
                
                if not para_text or len(para_text) < 20:
                    continue
                
                # FIXED: Robust page extraction
                pages = para.get("pages", [])
                if not pages and "page" in para:  # Fallback
                    pages = [para["page"]]
                
                # Filter out invalid pages and take first valid one
                valid_pages = [p for p in pages if p and p > 0]
                page_num = int(valid_pages[0]) if valid_pages else 1  # ← FIXED: Default to 1, not 0
                
                records.append({
                    "header": header_text,
                    "page": page_num,
                    "doc_name": label,
                    "chap_number": para_id or "Unnumbered",
                    "chapter_name": standard_name,
                    "para": para_text,
                    "para_number": para_id,
                    "preprocessed": simple_preprocess(para_text),
                    "publisher": "IFRS"
                })
        
        return pd.DataFrame.from_records(
            records,
            columns=["header", "page", "doc_name", "chap_number", "chapter_name", 
                     "para", "para_number", "preprocessed", "publisher"]
        )
    
    finally:
        doc.close()
# ===================== IFRS SPATIAL PARAGRAPH EXTRACTION (Refactored) =====================

# ---------- Patterns ----------
_NUM_TOKEN_RE = re.compile(
    r"""^(
        (\d+[A-Za-z]?)         # 1, 2A, 11B ...
        |\( ?[A-Za-z]\)        # (a), (A)
        |[A-Za-z][\.\)]        # a.  b)  A.  B)
        |B[C]?[.\)]?           # B, BC, B., BC)
        |[A-Za-z]{1,3}\d+[A-Za-z]? # A1, AB2, BC11, X9A
    )$""",
    re.VERBOSE | re.IGNORECASE,
)

_BULLET_RE = re.compile(
    r"""^(
        (\(?\d+[\)\.]?)      # 1, 1), (1)
        |(\(?[A-Za-z][\)\.]?)# (a), a), a.
        |[\u2022\-•▪■–—]     # bullet symbols
    )\s+
    """,
    re.VERBOSE,
)

_MAIN_PARA_RE = re.compile(r"^\d+[A-Za-z]?$")  # 1, 2, 5A, 11B

# ---------- Helpers ----------
def _rect_to_list(rect):
    if rect is None:
        return None
    return [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)]

def _y_center(bbox):
    return 0.5 * (bbox[1] + bbox[3])

def _guess_type(text, fontsize, is_header_by_rule):
    if not text.strip():
        return None
    if is_header_by_rule:
        return "heading"
    if fontsize >= 15 and len(text) < 140:
        return "heading"
    if _BULLET_RE.match(text.strip()):
        return "list_item"
    return "paragraph"

def _build_lines(words):
    """Build line aggregates from page.get_text('words') output."""
    lines_map = {}
    for w in words:
        key = (w[5], w[6])
        lines_map.setdefault(key, []).append(w)

    lines = []
    for key, ws in lines_map.items():
        ws.sort(key=lambda t: (t[0], t[7]))
        x0 = min(w[0] for w in ws); y0 = min(w[1] for w in ws)
        x1 = max(w[2] for w in ws); y1 = max(w[3] for w in ws)
        y_mid = 0.5 * (y0 + y1)
        tokens = [{"text": w[4], "x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3]} for w in ws]
        lines.append({"y_mid": y_mid, "bbox": [x0, y0, x1, y1], "tokens": tokens})
    lines.sort(key=lambda L: L["y_mid"])
    return lines

def _detect_gutter_for_page(blocks, page_width):
    """Adaptive gutter detection."""
    if not blocks:
        return (0.0, page_width * 0.50)

    left_edges = []
    for b in blocks:
        bbox = b.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            x0 = bbox[0]
            if x0 > 20:
                left_edges.append(x0)

    if not left_edges:
        return (0.0, page_width * 0.50)

    left_edges.sort()
    median_x0 = left_edges[len(left_edges) // 2]
    gutter_right = max(250.0, median_x0 - 10.0)
    gutter_right = min(gutter_right, page_width * 0.5)
    return (0.0, gutter_right)

def _first_numeric_token_in_gutter(line, gutter_right, num_re):
    """Return (token_text, bbox) if leftmost token in gutter is a pure integer."""
    candidates = [t for t in line["tokens"] if t["x1"] <= gutter_right]
    if not candidates:
        return None, None
    left = min(candidates, key=lambda t: t["x0"])
    tok = left["text"].strip()
    if num_re.match(tok):
        return tok, [left["x0"], left["y0"], left["x1"], left["y1"]]
    return None, None

def _attach_para_number_to_block(block_bbox, lines, gutter_right, num_re, y_tol=14.0):
    """Attach nearest numeric token in gutter to block by vertical proximity."""
    if not block_bbox or not lines:
        return None, None

    top_y = block_bbox[1]
    lo, hi = 0, len(lines) - 1
    best_i, best_d = None, 1e9
    while lo <= hi:
        mid = (lo + hi) // 2
        d = abs(lines[mid]["y_mid"] - top_y)
        if d < best_d:
            best_d, best_i = d, mid
        if lines[mid]["y_mid"] < top_y:
            lo = mid + 1
        else:
            hi = mid - 1
    if best_i is None or best_d > y_tol:
        return None, None

    start = max(0, best_i - 2)
    end = min(len(lines), best_i + 3)
    for j in range(start, end):
        tok, bb = _first_numeric_token_in_gutter(lines[j], gutter_right, num_re)
        if tok:
            return tok, bb
    return None, None

def _detect_header_rules(page, width_threshold_ratio=0.28, max_height=3.0):
    """Identify long, thin horizontal lines used as header underlines."""
    W = page.rect.width
    rules = []
    try:
        for d in page.get_drawings():
            rect = d.get("rect")
            if not isinstance(rect, fitz.Rect):
                continue
            w = rect.width
            h = rect.height
            if h <= max_height and w >= width_threshold_ratio * W:
                rules.append(rect)
    except Exception:
        pass
    return rules

def _mark_blocks_header_by_rules(blocks, rules):
    """Return set of block indices that are likely headings due to nearby rules."""
    header_block_ids = set()
    if not rules or not blocks:
        return header_block_ids

    bindex = []
    for i, b in enumerate(blocks):
        if "lines" not in b:
            continue
        bbox = b.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            by = _y_center(bbox)
            bindex.append((i, bbox, by))

    for r in rules:
        rbox = _rect_to_list(r)
        ry = _y_center(rbox)
        best = None
        best_dy = 1e9
        for i, bbox, by in bindex:
            overlap = min(rbox[2], bbox[2]) - max(rbox[0], bbox[0])
            if overlap <= 0:
                continue
            dy = abs(by - ry)
            if dy < best_dy:
                best_dy = dy
                best = i
        if best is not None and best_dy <= 35:
            header_block_ids.add(best)
    return header_block_ids

def _detect_drawn_digit_bbox_near_block(page, gutter_right, block_bbox, y_tol=14.0):
    """Fallback for paragraph numbers drawn as vector shapes."""
    if not block_bbox:
        return None
    top_y = block_bbox[1]
    y_min = top_y - y_tol
    y_max = top_y + y_tol

    try:
        for d in page.get_drawings():
            rect = d.get("rect")
            if not isinstance(rect, fitz.Rect):
                continue
            if rect.x1 > gutter_right and rect.x0 > gutter_right:
                continue
            w = rect.width; h = rect.height
            if 2 <= w <= 18 and 6 <= h <= 28:
                cy = 0.5 * (rect.y0 + rect.y1)
                if y_min <= cy <= y_max:
                    return _rect_to_list(rect)
    except Exception:
        pass
    return None

def _normalize_preserve_lines(txt: str) -> str:
    """Normalize while preserving line breaks."""
    if not isinstance(txt, str):
        txt = "" if txt is None else str(txt)

    lines = txt.splitlines()
    out = []
    for line in lines:
        line = re.sub(r"[ \t]+", " ", line)
        line = re.sub(r"\s+([,.;:])", r"\1", line)
        line = re.sub(r"([\)\]])([A-Za-z0-9])", r"\1 \2", line)
        line = re.sub(r"\(\s*([A-Za-z0-9]+)\s*\)", r"(\1)", line)
        out.append(line.strip())
    return "\n".join(out).strip()

def _is_main_para_id(pid):
    """Check if paragraph ID is a main paragraph (e.g., '1', '2A')."""
    if not pid:
        return False
    return bool(_MAIN_PARA_RE.match(pid.strip()))

def _y0_of(obj):
    bbox = obj.get("bbox")
    if not bbox or len(bbox) < 4:
        return 1e9
    return float(bbox[1])

def _is_header(obj):
    """Check if object is a header."""
    if obj.get("type") == "heading":
        return True
    attrs = obj.get("attrs", {}) or {}
    if attrs.get("header_marked_by_rule"):
        return True
    fs = attrs.get("fontsize") or 0
    txt = (obj.get("text") or "").strip()
    return bool(fs >= 14 and len(txt) <= 140)

# ---------- Main Extraction Function ----------
def extract_ifrs_objects_spatial(doc: fitz.Document) -> List[Dict]:
    """
    Extract objects from PDF with spatial paragraph number detection.
    Returns list of object dicts.
    """
    all_objects = []

    for page_num, page in enumerate(doc, start=1):
        tdict = page.get_text("dict")
        blocks = tdict.get("blocks", [])
        words = page.get_text("words")
        lines = _build_lines(words)
        
        gutter_left, gutter_right = _detect_gutter_for_page(blocks, page.rect.width)
        rules = _detect_header_rules(page)
        header_block_ids = _mark_blocks_header_by_rules(blocks, rules)

        for b_idx, b in enumerate(blocks):
            if "lines" not in b:
                continue

            spans_sizes = []
            text_parts = []
            for ln in b.get("lines", []):
                for s in ln.get("spans", []):
                    t = s.get("text", "")
                    if t:
                        text_parts.append(t)
                    if "size" in s:
                        spans_sizes.append(s["size"])

            block_text = " ".join(text_parts).strip()
            if not block_text:
                continue

            avg_font = round(sum(spans_sizes) / len(spans_sizes), 1) if spans_sizes else 0.0
            bbox = b.get("bbox")
            bbox_list = [round(x, 2) for x in bbox] if isinstance(bbox, (list, tuple)) else _rect_to_list(bbox)
            is_header_by_rule = (b_idx in header_block_ids)
            otype = _guess_type(block_text, avg_font, is_header_by_rule)

            para_number, number_bbox = _attach_para_number_to_block(
                bbox_list, lines, gutter_right, _NUM_TOKEN_RE, y_tol=14.0
            )

            para_number_drawn_bbox = None
            if para_number is None:
                para_number_drawn_bbox = _detect_drawn_digit_bbox_near_block(
                    page, gutter_right, bbox_list, y_tol=14.0
                )

            all_objects.append({
                "type": otype,
                "page": page_num,
                "bbox": bbox_list,
                "attrs": {
                    "fontsize": avg_font,
                    "header_marked_by_rule": bool(is_header_by_rule),
                    "para_number": para_number,
                    "para_number_bbox": [round(v, 2) for v in number_bbox] if number_bbox else None,
                    "para_number_drawn_bbox": para_number_drawn_bbox,
                    "gutter_band": [round(gutter_left, 2), round(gutter_right, 2)],
                },
                "text": block_text,
                "values": None
            })

        for r in rules:
            all_objects.append({
                "type": "header_rule",
                "page": page_num,
                "bbox": _rect_to_list(r),
                "attrs": {},
                "text": None,
                "values": None
            })

    return all_objects

# ---------- Build Sections Function ----------
def build_sections_mainparas(objects: List[Dict]) -> Dict:
    """Build sections by headers with main paragraph consolidation."""
    stream = sorted(
        (o for o in objects if o.get("type") in ("heading", "paragraph", "list_item")),
        key=lambda o: (int(o.get("page", 0)), _y0_of(o))
    )

    sections = []
    current_section = None
    current_para = None
    pending_pre_para_text = []

    def start_section(hobj):
        nonlocal current_section, current_para, pending_pre_para_text
        attrs = hobj.get("attrs", {}) or {}
        header = {
            "text": _normalize_preserve_lines(hobj.get("text", "") or ""),
            "page": hobj.get("page"),
            "bbox": hobj.get("bbox"),
            "fontsize": attrs.get("fontsize"),
        }
        current_section = {
            "header": header,
            "start_page": hobj.get("page"),
            "end_page": hobj.get("page"),
            "paragraphs": []
        }
        sections.append(current_section)
        current_para = None
        pending_pre_para_text = []

    def flush_current_para():
        nonlocal current_para
        if current_para and current_section:
            current_para["text"] = _normalize_preserve_lines(current_para["text"])
            current_para["pages"] = sorted(set(current_para["pages"]))
            current_section["paragraphs"].append(current_para)
        current_para = None

    def prepend_pending_to_current():
        nonlocal pending_pre_para_text, current_para
        if not pending_pre_para_text or not current_para:
            return
        pending_text = []
        pending_pages = []
        pending_bboxes = []
        for blk in pending_pre_para_text:
            pending_text.append(_normalize_preserve_lines(blk["text"]))
            pending_pages.append(blk["page"])
            if blk.get("bbox"):
                pending_bboxes.append(blk["bbox"])

        pre = _normalize_preserve_lines("\n".join([t for t in pending_text if t]))
        if pre:
            current_para["text"] = (pre + "\n\n" + current_para["text"]).strip()
            current_para["pages"].extend(pending_pages)
            current_para["bboxes"].extend(pending_bboxes)
        pending_pre_para_text = []

    for obj in stream:
        page = obj.get("page")
        if current_section:
            current_section["end_page"] = max(current_section["end_page"], page)

        if _is_header(obj):
            flush_current_para()
            start_section(obj)
            continue

        attrs = obj.get("attrs", {}) or {}
        pn = attrs.get("para_number")
        text = _normalize_preserve_lines(obj.get("text", "") or "")

        if current_section is None:
            start_section({
                "type": "heading",
                "text": "Document Start",
                "page": page,
                "bbox": obj.get("bbox"),
                "attrs": {"fontsize": None}
            })

        if _is_main_para_id(pn):
            flush_current_para()
            current_para = {
                "id": pn,
                "text": text,
                "pages": [page],
                "bboxes": [obj.get("bbox")] if obj.get("bbox") else [],
                "para_number_bbox": attrs.get("para_number_bbox")
            }
            prepend_pending_to_current()
            continue

        if current_para is not None:
            joiner = "\n" if (current_para["text"] and text) else ""
            current_para["text"] = (current_para["text"] + joiner + text).strip()
            current_para["pages"].append(page)
            if obj.get("bbox"):
                current_para["bboxes"].append(obj["bbox"])
        else:
            pending_pre_para_text.append({
                "page": page,
                "text": text,
                "bbox": obj.get("bbox")
            })

    if current_para:
        flush_current_para()
    if current_section and pending_pre_para_text:
        pre_text = _normalize_preserve_lines("\n".join(t["text"] for t in pending_pre_para_text if t.get("text")))
        pre_pages = sorted(set(t["page"] for t in pending_pre_para_text))
        pre_bboxes = [t["bbox"] for t in pending_pre_para_text if t.get("bbox")]
        current_section["paragraphs"].append({
            "id": None,
            "text": pre_text,
            "pages": pre_pages,
            "bboxes": pre_bboxes,
            "para_number_bbox": None
        })
        pending_pre_para_text = []

    return {"sections": sections}

# ---------- Consolidate Same-ID Paragraphs ----------
def consolidate_sameid_paragraphs(sections: List[Dict]) -> List[Dict]:
    """
    FIXED: Properly merge pages when consolidating paragraphs.
    """
    from collections import OrderedDict
    
    combined_sections = []
    for sec in sections:
        paras = sec.get("paragraphs", [])
        merged = OrderedDict()
        for p in paras:
            pid = p.get("id")
            text = _normalize_preserve_lines(p.get("text", "") or "")
            # FIXED: Handle both 'pages' (list) and 'page' (int) for backward compatibility
            pages_raw = p.get("pages", [])
            if not pages_raw and "page" in p:  # Fallback for old format
                pages_raw = [p["page"]]
            pages = sorted(set(pages_raw))
            
            if pid not in merged:
                merged[pid] = {"id": pid, "text": text, "pages": pages}
            else:
                merged[pid]["text"] = _normalize_preserve_lines(
                    (merged[pid]["text"] + "\n" + text).strip()
                )
                merged[pid]["pages"] = sorted(set(merged[pid]["pages"] + pages))
        
        sec_new = {
            "header": sec.get("header"),
            "start_page": sec.get("start_page"),
            "end_page": sec.get("end_page"),
            "paragraphs": list(merged.values())
        }
        combined_sections.append(sec_new)
    return combined_sections

# ---------- Main Pipeline Function ----------
def process_ifrs_pdf_spatial(pdf_path: str, label: str) -> pd.DataFrame:
    """
    Complete IFRS extraction pipeline with spatial paragraph detection.
    Returns DataFrame ready for FAISS indexing.
    """
    doc = fitz.open(pdf_path)
    #  Extract filename without extension to use as standard name
    standard_name = os.path.splitext(os.path.basename(pdf_path))[0]
    try:
        # Step 1: Extract objects with spatial para detection
        objects = extract_ifrs_objects_spatial(doc)
        
        # Step 2: Build sections with main paragraph grouping
        sections_data = build_sections_mainparas(objects)
        sections = sections_data.get("sections", [])
        
        # Step 3: Consolidate same-ID paragraphs
        sections = consolidate_sameid_paragraphs(sections)
        
        # Step 4: Convert to DataFrame
        records = []
        for section in sections:
            header_text = section.get("header", {}).get("text", "")
            
            for para in section.get("paragraphs", []):
                para_id = para.get("id")
                para_text = (para.get("text") or "").strip()
                
                if not para_text or len(para_text) < 20:
                    continue
                
                pages = para.get("pages", [])
                page_num = int(pages[0]) if pages else 0
                
                records.append({
                    "header": header_text,
                    "page": page_num,
                    "doc_name": label,
                    "chap_number": para_id or "Unnumbered",
                    "chapter_name": standard_name,
                    "para": para_text,
                    "para_number": para_id,  # ← NEW: dedicated paragraph number field
                    "preprocessed": simple_preprocess(para_text),
                    "publisher": "IFRS"
                })
        
        return pd.DataFrame.from_records(
            records,
            columns=["header", "page", "doc_name", "chap_number", "chapter_name", 
                     "para", "para_number", "preprocessed", "publisher"]
        )
    
    finally:
        doc.close()

# ======================== IFRS (NEW) — EnhancedPDFExtractor (PyMuPDF, UPDATED LOGIC) ========================
# ---- Your extractor & config, integrated inline ----

# Configuration class for customizable parameters
@dataclass
class ExtractionConfig:
    """Configuration for PDF extraction parameters"""
    # Smart header detection constants
    y_gap_max: float = 28.0
    overlap_ratio: float = 0.30
    bold_char_fraction: float = 0.70
    y_table_gap_max: float = 20.0
    table_overlap_ratio: float = 0.50

    # Font size thresholds
    large_font_threshold: float = 14.0
    medium_font_threshold: float = 12.0
    small_font_threshold: float = 10.0

    # Content thresholds
    min_chunk_length: int = 20
    blank_page_threshold: int = 50

    # Chapter / table patterns (unused for chapter if forcing name)
    chapter_patterns: List[str] = None
    table_start_patterns: List[str] = None
    table_header_patterns: List[str] = None

    def __post_init__(self):
        if self.chapter_patterns is None:
            self.chapter_patterns = []

        if self.table_start_patterns is None:
            self.table_start_patterns = [
                r'^Table[\u2014\u2013\-\—]\s*',
                r'^TABLE[\u2014\u2013\-\—]\s*',
                r'^Table\s*[\u2014\u2013\-\—].*requirements',
                r'^Table\s+\d+',
                r'^TABLE\s+\d+',
            ]

        if self.table_header_patterns is None:
            self.table_header_patterns = [
                r'Standard.*amendment.*When issued.*Effective date',
                r'Standard.*When issued.*Effective date',
                r'Standards.*Interpretations.*amended',
                r'Name.*Description.*Date',
                r'Item.*Description.*Amount',
            ]

BOLD_FLAG = getattr(fitz, "TEXT_FONT_BOLD", 16)

@dataclass
class TextBlock:
    text: str
    page_num: int
    bbox: Tuple[float, float, float, float]
    font_size: float
    font_flags: int
    font_name: str

@dataclass
class DocumentChunk:
    document_name: str
    address: str
    chapter_name: Optional[str]
    section_name: Optional[str]
    subsection_name: Optional[str]
    text_content: str
    page_number: int
    start_page: int
    end_page: int
    chunk_id: str

class EnhancedPDFExtractor:
    """
    Modified to support 'force_chapter_from_document_name':
    - Chapter detection is disabled; chapter is set to the document_name (usually the PDF filename).
    """
    def __init__(self, pdf_path: str, document_name: str = None, config: ExtractionConfig = None,
                 force_chapter_from_document_name: bool = True):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.document_name = document_name or "PDF Document"
        self.config = config or ExtractionConfig()
        self.text_blocks: List[TextBlock] = []
        self.chunks: List[DocumentChunk] = []
        self.force_chapter_from_document_name = force_chapter_from_document_name
        self._last_blank_pages: List[int] = []

    def _horizontal_overlap(self, a0: float, a1: float, b0: float, b1: float) -> float:
        return max(0.0, min(a1, b1) - max(a0, b0))

    def _collect_page_lines(self, page) -> List[Tuple[float, float, float]]:
        segs = []
        try:
            for d in page.get_drawings():
                for it in d.get("items", []):
                    if isinstance(it, tuple) and len(it) >= 3 and it[0] == "l":
                        p0, p1 = it[1], it[2]
                        if abs(p0.y - p1.y) < 0.5:  # horizontal line
                            y = (p0.y + p1.y) / 2.0
                            x0, x1 = (p0.x, p1.x) if p0.x <= p1.x else (p1.x, p0.x)
                            segs.append((y, x0, x1))
        except Exception as e:
            print(f"Warning: Error collecting page lines: {e}")
            return []

        segs.sort(key=lambda t: (round(t[0], 1), t[1], t[2]))
        merged: List[Tuple[float, float, float]] = []
        for y, x0, x1 in segs:
            if not merged or abs(merged[-1][0] - y) > 1.0:
                merged.append((y, x0, x1))
            else:
                oy, ox0, ox1 = merged[-1]
                if x0 <= ox1 + 2:
                    merged[-1] = (oy, min(ox0, x0), max(ox1, x1))
                else:
                    merged.append((y, x0, x1))
        return merged

    def debug_dump_blocks(self, label="RAW BLOCKS"):
        print(f"\n==== DEBUG DUMP: {label} ====")
        for i, block in enumerate(self.text_blocks):
            txt = block.text.strip().replace("\n", " ")
            print(
                f"[{i}] page={block.page_num}, size={block.font_size:.1f}, flags={block.font_flags}, text='{txt}'"
            )
        print("=======================================\n")

    def _consolidate_chunks_by_section(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        if not chunks:
            return chunks

        consolidated_chunks = []
        i = 0

        while i < len(chunks):
            current_chunk = chunks[i]
            group_chunks = [current_chunk]

            j = i + 1
            while j < len(chunks):
                next_chunk = chunks[j]
                if current_chunk.section_name is not None:
                    same_group = (
                        current_chunk.chapter_name == next_chunk.chapter_name and
                        current_chunk.section_name == next_chunk.section_name
                    )
                else:
                    same_group = (
                        current_chunk.chapter_name == next_chunk.chapter_name and
                        next_chunk.section_name is None
                    )

                if same_group:
                    group_chunks.append(next_chunk)
                    j += 1
                else:
                    break

            if len(group_chunks) == 1:
                consolidated_chunks.append(group_chunks[0])
            else:
                valid_start_pages = [c.start_page for c in group_chunks if c.start_page is not None]
                valid_end_pages = [c.end_page for c in group_chunks if c.end_page is not None]

                min_start_page = min(valid_start_pages) if valid_start_pages else group_chunks[0].page_number
                max_end_page = max(valid_end_pages) if valid_end_pages else group_chunks[-1].page_number

                combined_text = "\n\n".join(c.text_content for c in group_chunks)
                template = group_chunks[0]

                consolidated_chunk = DocumentChunk(
                    document_name=template.document_name,
                    address=template.address,
                    chapter_name=template.chapter_name,
                    section_name=template.section_name,
                    subsection_name=template.subsection_name,
                    text_content=combined_text,
                    page_number=min_start_page,
                    start_page=min_start_page,
                    end_page=max_end_page,
                    chunk_id=f"{template.chunk_id}_consolidated"
                )
                consolidated_chunks.append(consolidated_chunk)

                group_type = (
                    f"section: '{template.section_name}'" if template.section_name else f"chapter: '{template.chapter_name}'"
                )
                print(
                    f"  → Consolidated {len(group_chunks)} consecutive chunks for {group_type} "
                    f"(pages {min_start_page}-{max_end_page})"
                )

            i = j

        print(f"Consolidation complete: {len(chunks)} chunks → {len(consolidated_chunks)} chunks")
        return consolidated_chunks

    def extract_to_json(self, output_path: str = None, consolidate_sections: bool = True) -> List[Dict[str, Any]]:
        try:
            chunks = self.extract_hierarchical_structure()

            if consolidate_sections:
                print(f"\n=== CONSOLIDATING SECTIONS ===")
                chunks = self._consolidate_chunks_by_section(chunks)

            chunk_dicts = []
            for chunk in chunks:
                chunk_dicts.append({
                    "document_name": chunk.document_name,
                    "address": chunk.address,
                    "chapter_name": chunk.chapter_name,
                    "section_name": chunk.section_name,
                    "subsection_name": chunk.subsection_name,
                    "text_content": chunk.text_content,
                    "page_number": chunk.page_number,
                    "start_page": chunk.start_page,
                    "end_page": chunk.end_page,
                    "chunk_id": chunk.chunk_id
                })

            if output_path:
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(chunk_dicts, f, indent=2, ensure_ascii=False)

            return chunk_dicts

        except Exception as e:
            print(f"Error during extraction: {e}")
            raise

    def _has_table_pattern(self, block: TextBlock, page_lines: List[Tuple[float, float, float]]) -> bool:
        hx0, hy0, hx1, hy1 = block.bbox
        h_w = max(1.0, hx1 - hx0)

        has_top_line = False
        has_bottom_line = False

        for (y, x0, x1) in page_lines:
            line_w = max(1.0, x1 - x0)
            overlap = self._horizontal_overlap(hx0, hx1, x0, x1)
            overlap_ratio = overlap / min(h_w, line_w)
            if y < hy0 and (hy0 - y) <= self.config.y_table_gap_max and overlap_ratio >= self.config.table_overlap_ratio:
                has_top_line = True
            if y > hy1 and (y - hy1) <= self.config.y_table_gap_max and overlap_ratio >= self.config.table_overlap_ratio:
                has_bottom_line = True

        return has_top_line and has_bottom_line

    def _get_text_bold_ratio(self, block: TextBlock) -> float:
        if block.font_flags & BOLD_FLAG:
            return 1.0
        font_name = block.font_name.lower()
        if any(indicator in font_name for indicator in ['bold', 'heavy', 'black']):
            return 1.0
        return 0.0

    def _detect_blank_pages(self) -> List[int]:
        blank_pages = []
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            text = page.get_text().strip()
            cleaned_text = re.sub(r'©.*?Foundation.*?[A-Z]\d+', '', text)
            cleaned_text = re.sub(r'Conceptual Framework.*?©.*?Foundation', '', cleaned_text)
            cleaned_text = re.sub(r'^\d+\s*$', '', cleaned_text, flags=re.MULTILINE)
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
            if len(cleaned_text) < self.config.blank_page_threshold:
                blank_pages.append(page_num + 1)
        return blank_pages

    def _should_break_on_blank_page(self, current_page: int, blank_pages: List[int]) -> bool:
        if not blank_pages:
            return False
        return (current_page - 1) in blank_pages

    def extract_text_blocks(self) -> List[TextBlock]:
        text_blocks = []
        try:
            for page_num in range(len(self.doc)):
                page = self.doc[page_num]
                blocks = page.get_text("dict")

                for block in blocks["blocks"]:
                    if "lines" in block:
                        for line in block["lines"]:
                            for span in line["spans"]:
                                text = span["text"].strip()
                                if not text:
                                    continue
                                text_blocks.append(
                                    TextBlock(
                                        text=text,
                                        page_num=page_num + 1,
                                        bbox=span["bbox"],
                                        font_size=span["size"],
                                        font_flags=span["flags"],
                                        font_name=span["font"],
                                    )
                                )

            def merge_multiline_headings(blocks: List[TextBlock]) -> List[TextBlock]:
                merged = []
                buffer = None
                for tb in blocks:
                    if buffer is None:
                        buffer = tb
                        continue
                    if (
                        tb.page_num == buffer.page_num
                        and abs(tb.font_size - buffer.font_size) < 0.5
                        and tb.font_name == buffer.font_name
                        and tb.font_flags == buffer.font_flags
                        and tb.bbox[1] - buffer.bbox[3] < 5
                    ):
                        buffer.text += " " + tb.text
                        buffer.bbox = (
                            buffer.bbox[0],
                            buffer.bbox[1],
                            max(buffer.bbox[2], tb.bbox[2]),
                            tb.bbox[3],
                        )
                    else:
                        merged.append(buffer)
                        buffer = tb
                if buffer:
                    merged.append(buffer)
                return merged

            self.text_blocks = merge_multiline_headings(text_blocks)

        except Exception as e:
            print(f"Error extracting text blocks: {e}")
            raise

        return self.text_blocks

    # ------------- Section/Table/Paragraph helpers -------------
    # (Chapter detection intentionally unused when forcing chapter name)

    def is_table_start(self, block: TextBlock, context_blocks: List[TextBlock]) -> bool:
        text = block.text.strip()
        for pattern in self.config.table_start_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        combined_text = text
        for next_block in context_blocks[:3]:
            combined_text += " " + next_block.text.strip()
        for pattern in self.config.table_header_patterns:
            if re.search(pattern, combined_text, re.IGNORECASE):
                return True
        return False

    def is_table_content(self, block: TextBlock, in_table: bool, context_blocks: List[TextBlock],
                         current_index: int, all_blocks: List[TextBlock]) -> bool:
        if not in_table:
            return False
        text = block.text.strip()
        table_end_patterns = [
            r'^[A-Z][a-z]+\s+[A-Z][a-z]+.*[a-z]+$',
            r'^\d+\.\d+\s',
            r'^[A-Z\s]+$'
        ]
        for pattern in table_end_patterns:
            if re.match(pattern, text) and len(text) > 10:
                table_terms = ['amendment', 'january', 'ias', 'ifrs', 'effective', 'issued']
                if not any(keyword in text.lower() for keyword in table_terms):
                    return False
        return True

    def is_section_title(self, block: TextBlock, next_blocks: List[TextBlock],
                         in_table: bool = False, page_lines: List[Tuple[float,float,float]] = None) -> bool:
        if in_table:
            return False
        candidate = block.text.strip()
        has_graphic_underline = False
        if page_lines:
            bx0, by0, bx1, by1 = block.bbox
            for (ly, lx0, lx1) in page_lines:
                if by1 < ly < by1 + 10 and lx0 <= bx0 and lx1 >= bx1:
                    has_graphic_underline = True
                    break
        if not has_graphic_underline:
            return False
        if len(candidate) < 3 or len(candidate.split()) > 60:
            return False
        table_terms = ['standard', 'amendment', 'effective date', 'interpretations']
        if any(term in candidate.lower() for term in table_terms):
            return False
        bold_ratio = self._get_text_bold_ratio(block)
        if bold_ratio >= self.config.bold_char_fraction or block.font_size > self.config.medium_font_threshold:
            return True
        return False

    def is_toc_entry(self, block: TextBlock) -> bool:
        text = block.text.strip()
        if text.upper() == "CONTENTS":
            return True
        toc_patterns = [
            r'^from paragraph',
            r'^CHAPTER\s+\d+[—\-]',
            r'^[A-Z].*\s+\d+\.\d+$',
        ]
        for pat in toc_patterns:
            if re.match(pat, text, re.IGNORECASE):
                return True
        return False

    def _simple_section_detection(self, block: TextBlock, next_blocks: List[TextBlock]) -> bool:
        text = block.text.strip()
        if (block.font_flags & BOLD_FLAG or
            (self.config.small_font_threshold < block.font_size < 16 and
             not text.startswith(tuple('0123456789')) and
             len(text.split()) < 10)):
            return True
        return False

    def is_paragraph_number(self, text: str) -> bool:
        return bool(re.match(r'^(SP)?\d+\.\d+', text.strip()))

    def clean_text(self, text: str) -> str:
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'©.*?Foundation.*?[A-Z]\d+', '', text)
        text = re.sub(r'Conceptual Framework.*?©.*?Foundation', '', text)
        return text.strip()

    def extract_hierarchical_structure(self) -> List[DocumentChunk]:
        """
        Extract, but FORCE chapter to be the PDF's document_name (filename).
        All chapter-title detection is ignored.
        """
        self.text_blocks = self.extract_text_blocks()
        chunks: List[DocumentChunk] = []

        # Pre-set chapter from the document_name (usually the PDF filename)
        current_chapter = self.document_name if self.force_chapter_from_document_name else None
        current_section = None
        current_content: List[str] = []
        current_start_page: Optional[int] = None
        current_end_page: Optional[int] = None
        current_paragraph: Optional[str] = None
        in_table = False
        table_content: List[str] = []

        # Detect blank pages for content separation
        blank_pages = self._detect_blank_pages()
        self._last_blank_pages = blank_pages
        if blank_pages:
            print(f"Detected blank pages at: {blank_pages}")

        i = 0
        while i < len(self.text_blocks):
            block = self.text_blocks[i]
            text = block.text.strip()
            page_num = block.page_num

            # Collect page lines
            page = self.doc[page_num - 1]
            page_lines = self._collect_page_lines(page)

            if not text:
                i += 1
                continue

            # Blank page split
            if self._should_break_on_blank_page(page_num, blank_pages):
                if current_content and current_chapter:
                    chunk = self._create_chunk(
                        current_chapter, current_section, current_content,
                        current_start_page, current_end_page, current_paragraph
                    )
                    if chunk:
                        chunks.append(chunk)
                        print(f"  → Created chunk boundary due to blank page before page {page_num}")
                current_content, current_start_page, current_end_page, current_paragraph = [], None, None, None

            next_blocks = self.text_blocks[i+1:i+5] if i+1 < len(self.text_blocks) else []

            # TABLE handling
            if self.is_table_start(block, next_blocks):
                if current_content and current_chapter:
                    chunk = self._create_chunk(
                        current_chapter, current_section, current_content,
                        current_start_page, current_end_page, current_paragraph
                    )
                    if chunk:
                        chunks.append(chunk)
                in_table, table_content = True, [text]
                current_content = []
                current_start_page = current_start_page or page_num
                current_end_page = page_num

            elif in_table:
                if self.is_table_content(block, in_table, next_blocks, i, self.text_blocks):
                    table_content.append(text)
                    current_end_page = page_num
                else:
                    if table_content:
                        current_content.append(" ".join(table_content))
                        table_content = []
                    in_table = False
                    continue

            # CHAPTER handling: **DISABLED** (we force the chapter from filename)

            # SECTION handling (allowed)
            elif self.is_section_title(block, next_blocks, False, page_lines):
                if current_content and current_chapter:
                    chunk = self._create_chunk(
                        current_chapter, current_section, current_content,
                        current_start_page, current_end_page, current_paragraph
                    )
                    if chunk:
                        chunks.append(chunk)
                current_section = text
                current_content = []
                current_start_page = current_end_page = page_num
                current_paragraph = None

            # PARAGRAPH handling
            elif self.is_paragraph_number(text):
                if current_content and current_chapter:
                    chunk = self._create_chunk(
                        current_chapter, current_section, current_content,
                        current_start_page, current_end_page, current_paragraph
                    )
                    if chunk:
                        chunks.append(chunk)
                current_paragraph = text
                current_content = [text]
                current_start_page = current_end_page = page_num

            # Regular content
            else:
                current_start_page = current_start_page or page_num
                current_end_page = page_num
                current_content.append(text)

            # GRAPHIC underline split
            if current_content and current_chapter and page_lines:
                bx0, by0, bx1, by1 = block.bbox
                for (ly, lx0, lx1) in page_lines:
                    if by1 < ly < by1 + 12 and lx0 <= bx0 and lx1 >= bx1:
                        chunk = self._create_chunk(
                            current_chapter, current_section, current_content,
                            current_start_page, current_end_page, current_paragraph
                        )
                        if chunk:
                            chunks.append(chunk)
                            print(f"  → Closed section at graphic line on page {page_num}")
                        current_content, current_start_page, current_end_page, current_paragraph = [], None, None, None
                        break

            i += 1

        if in_table and table_content:
            current_content.append(" ".join(table_content))

        if current_content and current_chapter:
            chunk = self._create_chunk(
                current_chapter, current_section, current_content,
                current_start_page, current_end_page, current_paragraph
            )
            if chunk:
                chunks.append(chunk)

        chunks = self._merge_continued_chunks(chunks)
        return chunks

    def _clean_table_content(self, table_content: List[str]) -> str:
        full_table = ' '.join(table_content)
        if '\n\n' in full_table:
            table_parts = full_table.split('\n\n')
            full_table = table_parts[0]
        full_table = self.clean_text(full_table)
        full_table = re.sub(r'\s{3,}', ' | ', full_table)
        full_table = re.sub(r'\|\s*\|', '|', full_table)
        full_table = re.sub(r'\s+\|', ' |', full_table)
        full_table = re.sub(r'\|\s+', '| ', full_table)
        return full_table

    def _merge_continued_chunks(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        if not chunks:
            return chunks
        merged_chunks = []
        i = 0
        while i < len(chunks):
            current_chunk = chunks[i]
            text_content = current_chunk.text_content.strip()
            has_continued_forward = 'continued...' in text_content.lower()
            has_continued_backward = '...continued' in text_content.lower()
            if (has_continued_forward or has_continued_backward) and i + 1 < len(chunks):
                next_chunk = chunks[i + 1]
                cleaned_current = text_content
                if has_continued_forward:
                    pos = cleaned_current.lower().find('continued...')
                    if pos != -1:
                        cleaned_current = cleaned_current[:pos].strip()
                if has_continued_backward:
                    pos = cleaned_current.lower().find('...continued')
                    if pos != -1:
                        cleaned_current = cleaned_current[:pos].strip()
                next_text = next_chunk.text_content.strip()
                cleaned_next = re.sub(r'^\.{3,}continued\s*', '', next_text, flags=re.IGNORECASE)
                cleaned_next = re.sub(r'^continued\.{3,}\s*', '', cleaned_next, flags=re.IGNORECASE).strip()
                merged_content = cleaned_current + " " + cleaned_next
                merged_chunk = DocumentChunk(
                    document_name=current_chunk.document_name,
                    address=current_chunk.address,
                    chapter_name=current_chunk.chapter_name,
                    section_name=current_chunk.section_name,
                    subsection_name=current_chunk.subsection_name,
                    text_content=merged_content,
                    page_number=current_chunk.page_number,
                    start_page=current_chunk.start_page,
                    end_page=next_chunk.end_page,
                    chunk_id=current_chunk.chunk_id
                )
                merged_chunks.append(merged_chunk)
                i += 2
                continue
            merged_chunks.append(current_chunk)
            i += 1
        return merged_chunks

    def _create_chunk(self, chapter: str, section: Optional[str],
                      content: List[str], start_page: int, end_page: int, paragraph: Optional[str]) -> Optional[DocumentChunk]:
        if not content:
            return None
        text_content = ' '.join(content)
        table_indicators = ['Table\u2014', 'Table-', 'Table\u2013', 'TABLE\u2014', 'TABLE-', 'TABLE\u2013']
        if any(indicator in text_content for indicator in table_indicators):
            text_content = self._clean_table_content(content)
        else:
            text_content = self.clean_text(text_content)
        if len(text_content.strip()) < self.config.min_chunk_length:
            return None

        address_parts = [chapter]
        if paragraph:
            address_parts.append(paragraph)
        elif section:
            address_parts.append(section)
        address = ' '.join([address_parts[0]]) + (' > ' + ' > '.join(address_parts[1:]) if len(address_parts) > 1 else '')

        page_number = start_page
        chunk_id = self._generate_chunk_id(chapter, section, paragraph, text_content)

        return DocumentChunk(
            document_name=self.document_name,
            address=address,
            chapter_name=chapter,
            section_name=section,
            subsection_name=None,
            text_content=text_content,
            page_number=page_number,
            start_page=start_page,
            end_page=end_page,
            chunk_id=chunk_id
        )

    def _generate_chunk_id(self, chapter: str, section: Optional[str],
                           paragraph: Optional[str], content: str) -> str:
        id_parts = [
            re.sub(r'[^a-zA-Z0-9]', '_', chapter)[:20],
            paragraph or section or "section",
        ]
        content_hash = hashlib.md5(content.encode()).hexdigest()[:5]
        id_parts.append(content_hash)
        return '_'.join(id_parts)

    def close(self):
        self.doc.close()

# ---- IFRS adapter: convert EnhancedPDFExtractor output → DataFrame for FAISS ----
# def process_ifrs_pdf_to_df(pdf_path: str, label: str, custom_config: ExtractionConfig = None) -> pd.DataFrame:
#     """
#     Runs EnhancedPDFExtractor on an IFRS part and converts chunks
#     to the unified schema used by FAISS builder:
#     columns = ["header","page","doc_name","chap_number","para","preprocessed","publisher"]
#     """
#     extractor = EnhancedPDFExtractor(
#         pdf_path=pdf_path,
#         document_name=os.path.splitext(os.path.basename(pdf_path))[0],
#         config=custom_config or ExtractionConfig(
#             large_font_threshold=16.0,
#             medium_font_threshold=14.0,
#             small_font_threshold=11.0,
#             chapter_patterns=[]
#         )
#     )
#     try:
#         chunks = extractor.extract_to_json(output_path=None, consolidate_sections=True)
#     finally:
#         extractor.close()

#     records = []
#     for c in chunks:
#         para = (c.get("text_content") or "").strip()
#         if not para or len(para) < 20:
#             continue
#         section = (c.get("section_name") or "").strip()
#         chapter = (c.get("chapter_name") or "").strip()
#         address = (c.get("address") or "").strip()
#         header = section or address or chapter
#         chap_number = chapter or "Chapter ?"
#         page_num = int(c.get("page_number") or 0)

#         records.append({
#             "header": header,
#             "page": page_num,
#             "doc_name": label,                 # IFRS A / IFRS B / IFRS C
#             "chap_number": chap_number,
#             "chapter_name": chapter,           # NEW
#             "para": para,
#             "preprocessed": simple_preprocess(para),
#             "publisher": "IFRS"
#         })


#     df = pd.DataFrame.from_records(
#         records,
#         columns=["header","page","doc_name","chap_number","chapter_name","para","preprocessed","publisher"]
#     )

def process_ifrs_pdf_to_df(pdf_path: str, label: str, custom_config: ExtractionConfig = None) -> pd.DataFrame:
    """
    Runs spatial IFRS extraction and converts to DataFrame.
    """
    return process_ifrs_pdf_spatial(pdf_path, label)


# def process_ifrs_json_to_df(json_path: str, label: str) -> pd.DataFrame:
#     """
#     Reads a JSON (from EnhancedPDFExtractor.extract_to_json) and converts it to FAISS schema.
#     """
#     with open(json_path, "r", encoding="utf-8") as f:
#         chunks = json.load(f)

#     records = []
#     for c in chunks:
#         para = (c.get("text_content") or "").strip()
#         if not para or len(para) < 20:
#             continue
#         section = (c.get("section_name") or "").strip()
#         chapter = (c.get("chapter_name") or "").strip()
#         address = (c.get("address") or "").strip()
#         header = section or address or chapter or "—"
#         chap_number = chapter or "Chapter ?"
#         page_num = int(c.get("page_number") or c.get("start_page") or 0)
#         records.append({
#             "header": header,
#             "page": page_num,
#             "doc_name": label,
#             "chap_number": chap_number,
#             "chapter_name": chapter,      # NEW
#             "para": para,
#             "preprocessed": simple_preprocess(para),
#             "publisher": "IFRS"
#         })

#     return pd.DataFrame.from_records(
#         records,
#         columns=["header","page","doc_name","chap_number","chapter_name","para","preprocessed","publisher"]
#     )

def process_ifrs_json_to_df(json_path: str, label: str) -> pd.DataFrame:
    """
    Reads a sections JSON (from spatial pipeline) and converts to FAISS schema.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Extract filename as standard name
    standard_name = os.path.splitext(os.path.basename(json_path))[0]
    # Check if it's the new format (sections) or old format (chunks)
    if "sections" in data:
        # New spatial format
        records = []
        for section in data.get("sections", []):
            header_text = section.get("header", {}).get("text", "")
            
            for para in section.get("paragraphs", []):
                para_id = para.get("id")
                para_text = (para.get("text") or "").strip()
                
                if not para_text or len(para_text) < 20:
                    continue
                
                pages = para.get("pages", [])
                page_num = int(pages[0]) if pages else 0
                
                records.append({
                    "header": header_text,
                    "page": page_num,
                    "doc_name": label,
                    "chap_number": para_id or "Unnumbered",
                    "chapter_name": standard_name,
                    "para": para_text,
                    "para_number": para_id,  # ← NEW
                    "preprocessed": simple_preprocess(para_text),
                    "publisher": "IFRS"
                })
        
        return pd.DataFrame.from_records(
            records,
            columns=["header", "page", "doc_name", "chap_number", "chapter_name", 
                     "para", "para_number", "preprocessed", "publisher"]
        )
    else:
        # Old format (fallback to original logic)
        chunks = data  # assuming it's a list of chunks
        records = []
        for c in chunks:
            para = (c.get("text_content") or "").strip()
            if not para or len(para) < 20:
                continue
            section = (c.get("section_name") or "").strip()
            chapter = (c.get("chapter_name") or "").strip()
            address = (c.get("address") or "").strip()
            header = section or address or chapter or "–"
            chap_number = chapter or "Chapter ?"
            page_num = int(c.get("page_number") or c.get("start_page") or 0)
            records.append({
                "header": header,
                "page": page_num,
                "doc_name": label,
                "chap_number": chap_number,
                "chapter_name": chapter,
                "para": para,
                "para_number": None,  # Old format doesn't have this
                "preprocessed": simple_preprocess(para),
                "publisher": "IFRS"
            })

        return pd.DataFrame.from_records(
            records,
            columns=["header", "page", "doc_name", "chap_number", "chapter_name", 
                     "para", "para_number", "preprocessed", "publisher"]
        )



def process_ifrs_upload_to_df(uploaded_file, label: str) -> pd.DataFrame:
    """
    Accepts an uploaded IFRS file that can be either a PDF or a JSON
    (produced earlier by EnhancedPDFExtractor.extract_to_json()).
    Returns a DataFrame compatible with build_faiss_from_df_unified().
    """
    name = uploaded_file.name
    ext = os.path.splitext(name)[1].lower()
    tmp_path = _save_uploaded_to_tmp(uploaded_file, suffix=ext or ".bin")

    try:
        if ext == ".json":
            result = process_ifrs_json_to_df(tmp_path, label)
        elif ext == ".pdf":
            result = process_ifrs_pdf_to_df(tmp_path, label)
        else:
            raise ValueError(f"Unsupported IFRS file type: {ext}. Please upload .pdf or .json")
        return result
    finally:
        # Clean up the temporary file
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception as cleanup_error:
                print(f"[IFRS {label}] Warning: Could not delete temp file {tmp_path}: {cleanup_error}")

# ---------- IFRS helpers: multi-file, folder & ZIP adapters ----------
# def process_ifrs_path_to_df(path: str, label: str) -> pd.DataFrame:
#     """
#     Accepts a local file path to a PDF or JSON produced by EnhancedPDFExtractor.
#     Returns a FAISS-ready DataFrame.
#     """
#     ext = os.path.splitext(path)[1].lower()
#     if ext == ".json":
#         return process_ifrs_json_to_df(path, label)
#     elif ext == ".pdf":
#         return process_ifrs_pdf_to_df(path, label)
#     else:
#         return pd.DataFrame(columns=["header","page","doc_name","chap_number","chapter_name","para","preprocessed","publisher"])

def process_ifrs_path_to_df(path: str, label: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        return process_ifrs_json_to_df(path, label)
    elif ext == ".pdf":
        return process_ifrs_pdf_spatial_v2(path, label)  # ← UPDATED
    else:
        return pd.DataFrame(columns=["header","page","doc_name","chap_number","chapter_name","para","preprocessed","publisher"])

def process_ifrs_folder_to_df(folder_or_zip: str, label: str) -> pd.DataFrame:
    """
    Accepts either a folder path or a ZIP file path.
    - If it's a folder: scans recursively for *.pdf / *.json.
    - If it's a zip: extracts to temp dir, then scans inside.
    Returns a FAISS-ready DataFrame.
    """
    import shutil

    # Track if we need to cleanup temp directory and the ZIP file itself
    cleanup_tmp_dir = False
    cleanup_zip_file = False
    tmp_dir = None
    zip_file_path = None

    # Handle ZIP paths
    if folder_or_zip.lower().endswith(".zip"):
        if not os.path.isfile(folder_or_zip):
            raise FileNotFoundError(f"ZIP not found: {folder_or_zip}")

        zip_file_path = folder_or_zip
        # Check if the ZIP is in a temp directory (uploaded file) - then we should clean it up
        if 'temp' in zip_file_path.lower() or 'tmp' in zip_file_path.lower():
            cleanup_zip_file = True

        tmp_dir = tempfile.mkdtemp(prefix=f"ifrs_{label.lower()}_")
        cleanup_tmp_dir = True

        try:
            with zipfile.ZipFile(folder_or_zip, "r") as zf:
                zf.extractall(tmp_dir)
            folder_path = tmp_dir
            print(f"[IFRS {label}] extracted ZIP to: {folder_path}")
        except Exception as e:
            # Clean up temp dir if extraction failed
            if cleanup_tmp_dir and tmp_dir and os.path.exists(tmp_dir):
                try:
                    shutil.rmtree(tmp_dir)
                except Exception:
                    pass
            raise RuntimeError(f"Failed to extract ZIP {folder_or_zip}: {e}")
    else:
        folder_path = folder_or_zip

    if not os.path.isdir(folder_path):
        raise FileNotFoundError(f"Folder not found: {folder_path}")

    try:
        files = []
        for root, _, fns in os.walk(folder_path):
            for fn in fns:
                if fn.lower().endswith((".pdf", ".json")):
                    files.append(os.path.join(root, fn))
        files.sort()

        parts = []
        for p in files:
            try:
                parts.append(process_ifrs_path_to_df(p, label))
            except Exception as e:
                print(f"[IFRS {label}] Skipping {p}: {e}")

        result = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
            columns=["header","page","doc_name","chap_number","chapter_name","para","preprocessed","publisher"]
        )

        return result

    finally:
        # Clean up temporary directory if we created one
        if cleanup_tmp_dir and tmp_dir and os.path.exists(tmp_dir):
            try:
                shutil.rmtree(tmp_dir)
                print(f"[IFRS {label}] cleaned up temp directory: {tmp_dir}")
            except Exception as cleanup_error:
                print(f"[IFRS {label}] Warning: Could not clean up temp directory {tmp_dir}: {cleanup_error}")

        # Clean up the ZIP file if it was a temp upload
        if cleanup_zip_file and zip_file_path and os.path.exists(zip_file_path):
            try:
                os.unlink(zip_file_path)
                print(f"[IFRS {label}] cleaned up temp ZIP file: {zip_file_path}")
            except Exception as cleanup_error:
                print(f"[IFRS {label}] Warning: Could not delete temp ZIP {zip_file_path}: {cleanup_error}")

def process_ifrs_uploads_to_df(uploaded_files, label: str) -> pd.DataFrame:
    """
    Accepts multiple uploaded files (pdf/json) from Streamlit and merges into one DF.
    """
    if not uploaded_files:
        return pd.DataFrame(columns=["header","page","doc_name","chap_number","chapter_name","para","preprocessed","publisher"])

    parts = []
    for f in uploaded_files:
        try:
            df = process_ifrs_upload_to_df(f, label)  # uses your existing upload handler
            parts.append(df)
        except Exception as e:
            print(f"[IFRS {label}] Skipping upload '{getattr(f, 'name', '?')}': {e}")
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
        columns=["header","page","doc_name","chap_number","chapter_name","para","preprocessed","publisher"]
    )

def process_ifrs_zip_upload_to_df(uploaded_zip, label: str) -> pd.DataFrame:
    """
    Accepts a Streamlit-uploaded .zip for an IFRS part,
    saves it to a temp file, and routes to process_ifrs_folder_to_df()
    which handles .zip extraction -> scan -> DataFrame.
    """
    zip_path = _save_uploaded_to_tmp(uploaded_zip, suffix=".zip")
    try:
        result = process_ifrs_folder_to_df(zip_path, label)  # accepts .zip paths
        return result
    finally:
        # Clean up the temporary ZIP file
        if os.path.exists(zip_path):
            try:
                os.unlink(zip_path)
                print(f"[IFRS {label}] cleaned up temp ZIP file: {zip_path}")
            except Exception as cleanup_error:
                print(f"[IFRS {label}] Warning: Could not delete temp ZIP {zip_path}: {cleanup_error}")

