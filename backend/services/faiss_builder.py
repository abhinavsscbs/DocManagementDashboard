"""
Unified FAISS index builder for all document types (EY, PwC, IFRS).
Builds vector embeddings and creates searchable indexes.
"""

import os
import pandas as pd

from utils.config import get_model_name


def build_faiss_from_df_unified(df: pd.DataFrame, index_dir: str, model_name: str = None):
    """
    Build a FAISS index from a DataFrame of document chunks.

    Args:
        df: DataFrame with columns: para, header, doc_name, publisher, chap_number,
            chapter_name, page, para_number (optional)
        index_dir: Directory to save the FAISS index
        model_name: Embedding model name (default from config)

    Returns:
        FAISS vectorstore object or None if no data
    """
    try:
        from langchain_community.vectorstores import FAISS
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from langchain_community.vectorstores.utils import DistanceStrategy
    except Exception:
        from langchain.vectorstores import FAISS
        from langchain.embeddings.huggingface import HuggingFaceEmbeddings
        from langchain.vectorstores.utils import DistanceStrategy

    if model_name is None:
        model_name = get_model_name()

    os.makedirs(index_dir, exist_ok=True)
    if df.empty:
        print("� No chunks to index. Skipping FAISS build.")
        return None

    texts, metas = [], []
    for _, r in df.iterrows():
        base_text = (r.get("para") or "").strip()
        if not base_text:
            continue
        hdr = (r.get("header") or "").strip()
        txt = f"{hdr}  {base_text}" if hdr else base_text
        texts.append(txt)
        metas.append({
            "doc_name": r.get("doc_name"),
            "publisher": r.get("publisher"),
            "chapter": r.get("chap_number"),
            "chapter_name": r.get("chapter_name") or r.get("chap_number"),
            "header": hdr,
            "page": int(r.get("page") or 0),
            "para_number": r.get("para_number"),  # Optional for IFRS
        })

    if not texts:
        print("� No non-empty texts after selection. Skipping FAISS build.")
        return None

    embeddings = HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True}
    )
    vectordb = FAISS.from_texts(
        texts=texts,
        embedding=embeddings,
        metadatas=metas,
        distance_strategy=DistanceStrategy.COSINE
    )
    vectordb.save_local(index_dir)
    print(f" FAISS index built and saved to: {index_dir}")
    return vectordb
