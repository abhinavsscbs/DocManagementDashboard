"""
Helper functions shared across all processors.
"""


def build_chapter_spans(toc_headers, header_map, total_pages):
    """Build chapter spans from TOC headers and their detected locations."""
    valid = [(h, header_map[h][1]) for h in toc_headers if header_map[h][0] == " Found" and header_map[h][1]]
    valid.sort(key=lambda x: x[1])
    spans = []
    for i, (h, start_pg) in enumerate(valid):
        end_pg = (valid[i+1][1] - 1) if i+1 < len(valid) else total_pages
        spans.append({"chapter_header": h, "start_page": start_pg, "end_page": end_pg})
    return spans
