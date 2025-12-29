"""Model download and management for Interpreter.

This module handles downloading and caching of ML models:
- MeikiOCR: ONNX models for Japanese game text OCR
- Sugoi V4: CTranslate2 model for Japanese to English translation
"""

import os
import zipfile
from pathlib import Path

import requests
from tqdm import tqdm

# Model URLs (hosted on HuggingFace or similar)
MODELS = {
    "sugoi-v4-ja-en-ct2": {
        "url": "https://huggingface.co/YOUR_USERNAME/sugoi-v4-ja-en-ct2/resolve/main/model.zip",
        "size_mb": 1100,
        "description": "Sugoi V4 Japanese to English translation model",
    },
}

# Default models directory
DEFAULT_MODELS_DIR = Path.home() / ".interpreter" / "models"


def get_models_dir() -> Path:
    """Get the models directory, creating it if needed."""
    models_dir = Path(os.environ.get("INTERPRETER_MODELS_DIR", DEFAULT_MODELS_DIR))
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def download_file(url: str, dest: Path, desc: str = "Downloading") -> None:
    """Download a file with progress bar."""
    response = requests.get(url, stream=True)
    response.raise_for_status()

    total_size = int(response.headers.get("content-length", 0))

    with open(dest, "wb") as f:
        with tqdm(total=total_size, unit="B", unit_scale=True, desc=desc) as pbar:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                pbar.update(len(chunk))


def extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """Extract a zip file."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)


def ensure_model(model_name: str, models_dir: Path | None = None) -> Path:
    """Ensure a model is downloaded and return its path.

    Args:
        model_name: Name of the model (e.g., "sugoi-v4-ja-en-ct2")
        models_dir: Optional custom models directory

    Returns:
        Path to the model directory
    """
    if models_dir is None:
        models_dir = get_models_dir()

    model_path = models_dir / model_name

    if model_path.exists():
        return model_path

    if model_name not in MODELS:
        raise ValueError(f"Unknown model: {model_name}")

    model_info = MODELS[model_name]
    print(f"Downloading {model_info['description']}...")
    print(f"Size: ~{model_info['size_mb']} MB")

    # Download zip file
    zip_path = models_dir / f"{model_name}.zip"
    download_file(model_info["url"], zip_path, desc=model_name)

    # Extract
    print("Extracting...")
    extract_zip(zip_path, models_dir)

    # Clean up zip
    zip_path.unlink()

    if not model_path.exists():
        raise RuntimeError(f"Model extraction failed: {model_path} not found")

    print(f"Model ready: {model_path}")
    return model_path


def ensure_all_models(models_dir: Path | None = None) -> dict[str, Path]:
    """Ensure all required models are downloaded.

    Returns:
        Dictionary mapping model names to their paths
    """
    if models_dir is None:
        models_dir = get_models_dir()

    paths = {}
    for model_name in MODELS:
        paths[model_name] = ensure_model(model_name, models_dir)

    return paths


def get_sugoi_model_path(models_dir: Path | None = None) -> Path:
    """Get path to Sugoi V4 translation model."""
    return ensure_model("sugoi-v4-ja-en-ct2", models_dir)
