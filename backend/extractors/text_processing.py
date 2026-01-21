"""Text processing and normalization utilities."""
import re
from typing import List


def normalize(text: str) -> str:
    """Basic text normalization."""
    text = text.replace("–", "-")
    text = re.sub(r'\bchapter\s*\d*\b', '', text, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', text.strip().lower())


def simple_tokens(text: str) -> List[str]:
    """Tokenize text with stopword removal."""
    STOPWORDS = {
        "the", "and", "a", "an", "to", "of", "in", "for", "on", "with",
        "as", "by", "at", "is", "are", "be", "or", "that", "this", "it", "from"
    }
    text = text.lower()
    text = re.sub(r"[^\w\s\-]", " ", text)  # keep hyphen/en dash
    return [t for t in text.split() if t and t not in STOPWORDS]


def simple_stem(word: str) -> str:
    """Simple suffix-based stemming."""
    for suf in ("ing", "ed", "ly", "es", "s"):
        if word.endswith(suf) and len(word) > len(suf) + 2:
            return word[:-len(suf)]
    return word


def simple_preprocess(text: str) -> str:
    """Preprocess text for search: tokenize, stem, join."""
    return " ".join(simple_stem(w) for w in simple_tokens(text))


def normalize_preserve_lines(txt: str) -> str:
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
