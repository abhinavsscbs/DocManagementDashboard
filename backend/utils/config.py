"""Configuration loader utility."""
import yaml
import os
from pathlib import Path
from typing import Dict, Any

_config_cache = None

def load_config(config_path: str = None) -> Dict[str, Any]:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config file. If None, uses default backend/config.yaml

    Returns:
        Dictionary containing configuration
    """
    global _config_cache

    if _config_cache is not None:
        return _config_cache

    if config_path is None:
        # Default to backend/config.yaml
        backend_dir = Path(__file__).parent.parent
        config_path = backend_dir / "config.yaml"

    with open(config_path, 'r') as f:
        _config_cache = yaml.safe_load(f)

    return _config_cache

def get_faiss_dir(key: str) -> str:
    """Get FAISS directory path for a specific key.

    Args:
        key: One of 'ifrs_a', 'ifrs_b', 'ifrs_c', 'ey', 'pwc', 'combined' (case-insensitive)

    Returns:
        Directory path as string
    """
    config = load_config()
    # Handle case-insensitive key lookup
    key_lower = key.lower()
    return config['faiss'][key_lower]

def get_doc_name(key: str) -> str:
    """Get document name for a specific key.

    Args:
        key: One of 'ey', 'pwc', 'ifrs_a', 'ifrs_b', 'ifrs_c' (case-insensitive)

    Returns:
        Document display name
    """
    config = load_config()
    # Handle case-insensitive key lookup
    key_lower = key.lower()
    return config['document_names'][key_lower]

def get_model_name() -> str:
    """Get the embedding model name."""
    config = load_config()
    return config['processing']['model_name']

def get_max_upload_size() -> int:
    """Get maximum upload size in MB."""
    config = load_config()
    return config['processing']['max_upload_size_mb']

def get_cors_origins() -> list:
    """Get list of allowed CORS origins."""
    config = load_config()
    return config['server']['cors_origins']

def reload_config():
    """Force reload of configuration (useful for testing)."""
    global _config_cache
    _config_cache = None
