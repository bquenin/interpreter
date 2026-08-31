"""Pinned translation-model adapters used by the benchmark runner."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import platform
import random
import sys
import types
from pathlib import Path
from typing import Any

from benchlib import BenchmarkError, fingerprint, sha256_file

_GPU_LIBRARY_HANDLES: list[Any] = []


class _SilentLogger:
    def __getattr__(self, _name: str):
        return lambda *args, **kwargs: None


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BenchmarkError(f"Could not load application module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_application_translator(repo_root: Path):
    """Load production translate.py without importing the GUI or capture stack."""

    source_root = repo_root / "src" / "interpreter"
    translate_path = source_root / "translate.py"
    if not translate_path.is_file():
        raise BenchmarkError(f"Interpreter translation source not found under {repo_root}")

    package = types.ModuleType("interpreter")
    package.__path__ = [str(source_root)]
    sys.modules["interpreter"] = package

    log_module = types.ModuleType("interpreter.log")
    log_module.get_logger = lambda *_args, **_kwargs: _SilentLogger()
    sys.modules["interpreter.log"] = log_module

    models_module = types.ModuleType("interpreter.models")

    class ModelLoadError(Exception):
        pass

    models_module.ModelLoadError = ModelLoadError
    sys.modules["interpreter.models"] = models_module
    return _load_module("interpreter.translate", translate_path).Translator


def setup_application_gpu(repo_root: Path) -> bool:
    """Run the same platform GPU bootstrap that the GUI performs at startup."""

    platform_module = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(platform.system())
    if platform_module is None:
        return False
    path = repo_root / "src" / "interpreter" / "gpu" / f"{platform_module}.py"
    module = _load_module(f"interpreter.gpu.{platform_module}", path)
    return bool(module.setup())


def setup_isolated_gpu_packages() -> list[str]:
    """Register CUDA pip-package libraries across uv's overlay paths.

    The application virtual environment keeps dependencies in one
    site-packages directory. ``uv run --isolated --with`` may expose several
    overlay directories, so the application's first-directory scan cannot see
    every NVIDIA package. Candidate environments need this equivalent fallback
    to exercise the device they would use when installed in the application.
    """

    system = platform.system()
    subdirectory = "bin" if system == "Windows" else "lib" if system == "Linux" else None
    if subdirectory is None:
        return []
    directories = sorted(
        {
            str(candidate.resolve())
            for entry in sys.path
            for package_root in [Path(entry) / "nvidia"]
            if package_root.is_dir()
            for package in package_root.iterdir()
            if package.is_dir()
            for candidate in [package / subdirectory]
            if candidate.is_dir()
        }
    )
    if not directories:
        return []

    variable = "PATH" if system == "Windows" else "LD_LIBRARY_PATH"
    current = os.environ.get(variable, "")
    existing = {value.casefold() for value in current.split(os.pathsep) if value}
    additions = [value for value in directories if value.casefold() not in existing]
    if additions:
        os.environ[variable] = os.pathsep.join([*additions, current])

    if system == "Windows":
        for directory in directories:
            try:
                _GPU_LIBRARY_HANDLES.append(os.add_dll_directory(directory))
            except (OSError, AttributeError):
                pass
    else:
        import ctypes

        for name in ("libcublas.so.12", "libcublasLt.so.12", "libcudnn.so.9"):
            for directory in directories:
                candidate = Path(directory) / name
                if not candidate.is_file():
                    continue
                try:
                    _GPU_LIBRARY_HANDLES.append(ctypes.CDLL(str(candidate), mode=ctypes.RTLD_GLOBAL))
                except OSError:
                    pass
                break
    return directories


def normalize_display_output(text: str) -> str:
    """Apply the output normalization currently embedded in Translator.translate."""

    return (
        text.strip()
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2013", "-")
        .replace("\u2014", "--")
        .replace("\u2212", "-")
        .replace("\u00a0", " ")
        .replace("\u2026", "...")
    )


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _snapshot_revision(path: Path) -> str | None:
    parts = path.resolve().parts
    try:
        return parts[parts.index("snapshots") + 1]
    except (ValueError, IndexError):
        return None


def _snapshot_metadata(path: Path) -> dict[str, Any]:
    files = []
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = file_path.relative_to(path).as_posix()
        files.append(
            {
                "path": relative,
                "bytes": file_path.stat().st_size,
                "sha256": sha256_file(file_path),
            }
        )
    return {
        "resolved_revision": _snapshot_revision(path),
        "bytes": sum(item["bytes"] for item in files),
        "fingerprint": fingerprint(files),
        "files": files,
    }


def _verify_revision(path: Path, model: dict[str, Any]) -> None:
    expected = model.get("revision")
    actual = _snapshot_revision(path)
    if expected and actual != expected:
        raise BenchmarkError(
            f"Loaded {model['repo_id']} revision {actual or 'unknown'}, but models.json pins {expected}"
        )


def _download_snapshot(model: dict[str, Any], *, allow_patterns: list[str] | None = None) -> Path:
    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import GatedRepoError
    except ImportError as exc:
        raise BenchmarkError("The model environment must provide huggingface-hub") from exc

    try:
        path = Path(
            snapshot_download(
                repo_id=model["repo_id"],
                revision=model["revision"],
                allow_patterns=allow_patterns,
            )
        )
    except GatedRepoError as exc:
        raise BenchmarkError(
            f"{model['repo_id']} is gated. Accept its license on Hugging Face and set HF_TOKEN before retrying."
        ) from exc
    _verify_revision(path, model)
    return path


class BaseAdapter:
    """Small common interface; each adapter represents a deployable inference profile."""

    prompt_contract = "plain Japanese source text"

    def __init__(
        self,
        model_id: str,
        model: dict[str, Any],
        repo_root: Path,
        device: str = "auto",
        generation_seed: int = 1729,
    ):
        self.model_id = model_id
        self.model = model
        self.repo_root = repo_root
        self.device_preference = device
        self.generation_seed = generation_seed
        self.device = "unknown"
        self.compute_type: str | None = None
        self.model_path: Path | None = None
        self.runtime_setup: dict[str, Any] = {}

    def load(self) -> None:
        raise NotImplementedError

    def translate(self, text: str) -> str:
        raise NotImplementedError

    def clear_cache(self) -> None:
        """Clear application-level memoization before a measured translation."""

    def synchronize(self) -> None:
        """Wait for asynchronous device work before stopping a timer."""

    def metadata(self) -> dict[str, Any]:
        if self.model_path is None:
            raise BenchmarkError("Adapter metadata requested before the model was loaded")
        return {
            "id": self.model_id,
            "registry": self.model,
            "repo_id": self.model["repo_id"],
            "adapter": self.model["adapter"],
            "device_preference": self.device_preference,
            "device": self.device,
            "compute_type": self.compute_type,
            "prompt_contract": self.prompt_contract,
            "generation": self.model["generation"],
            "generation_seed": self.generation_seed,
            "runtime_setup": self.runtime_setup,
            "artifacts": _snapshot_metadata(self.model_path),
        }


class ProductionAdapter(BaseAdapter):
    prompt_contract = "exact src/interpreter/translate.py::Translator.translate path; cache cleared per call"

    def load(self) -> None:
        if self.device_preference != "auto":
            raise BenchmarkError("The production adapter uses Translator.load's exact automatic device selection")
        self.runtime_setup["application_gpu_setup"] = setup_application_gpu(self.repo_root)
        Translator = load_application_translator(self.repo_root)
        self.translator = Translator()
        self.translator.load()
        self.model_path = Path(self.translator._model_path)
        _verify_revision(self.model_path, self.model)
        engine = self.translator._translator
        self.device = str(getattr(engine, "device", "unknown"))
        self.compute_type = str(getattr(engine, "compute_type", "unknown"))

    def clear_cache(self) -> None:
        self.translator._cache._cache.clear()

    def translate(self, text: str) -> str:
        prediction, was_cached = self.translator.translate(text)
        if was_cached:
            raise BenchmarkError("Production translation unexpectedly used its fuzzy cache during a measured call")
        return prediction


class QuickMTAdapter(BaseAdapter):
    prompt_contract = "plain source passed through the repository's source SentencePiece model"

    def load(self) -> None:
        self.runtime_setup["application_gpu_setup"] = setup_application_gpu(self.repo_root)
        self.runtime_setup["isolated_gpu_package_directories"] = setup_isolated_gpu_packages()
        try:
            import ctranslate2
            import sentencepiece as sentencepiece
        except ImportError as exc:
            raise BenchmarkError("QuickMT requires ctranslate2 and sentencepiece") from exc

        self.model_path = _download_snapshot(
            self.model,
            allow_patterns=[
                "config.json",
                "model.bin",
                "source_vocabulary.json",
                "target_vocabulary.json",
                "src.spm.model",
                "tgt.spm.model",
            ],
        )
        requested = self.device_preference
        if requested not in {"auto", "cuda", "cpu"}:
            raise BenchmarkError(f"Invalid device: {requested}")
        attempts = [requested] if requested != "auto" else ["cuda", "cpu"]
        last_error: Exception | None = None
        for device in attempts:
            try:
                translator = ctranslate2.Translator(str(self.model_path), device=device)
                translator.translate_batch([["テスト"]], beam_size=1, max_decoding_length=8)
                self.translator = translator
                self.device = device
                self.compute_type = str(getattr(translator, "compute_type", "unknown"))
                break
            except Exception as exc:  # CUDA availability is ultimately verified by inference.
                last_error = exc
        else:
            raise BenchmarkError(f"Could not load QuickMT on {attempts}: {last_error}") from last_error

        self.source_tokenizer = sentencepiece.SentencePieceProcessor(
            model_proto=(self.model_path / "src.spm.model").read_bytes()
        )
        self.target_tokenizer = sentencepiece.SentencePieceProcessor(
            model_proto=(self.model_path / "tgt.spm.model").read_bytes()
        )

    def translate(self, text: str) -> str:
        tokens = self.source_tokenizer.EncodeAsPieces(text)
        result = self.translator.translate_batch(
            [tokens],
            beam_size=self.model["generation"]["beam_size"],
            max_decoding_length=self.model["generation"]["max_decoding_length"],
        )[0]
        prediction = self.target_tokenizer.DecodePieces(result.hypotheses[0])
        return normalize_display_output(prediction)


class TransformersAdapter(BaseAdapter):
    add_generation_prompt = True

    def tokenizer_kwargs(self) -> dict[str, Any]:
        return {}

    def load(self) -> None:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise BenchmarkError("This adapter requires torch and transformers") from exc

        self.torch = torch
        self.model_path = _download_snapshot(self.model)
        requested = self.device_preference
        if requested not in {"auto", "cuda", "cpu"}:
            raise BenchmarkError(f"Invalid device: {requested}")
        if requested == "cuda" and not torch.cuda.is_available():
            raise BenchmarkError("CUDA was requested but torch.cuda.is_available() is false")
        self.device = "cuda" if requested == "cuda" or (requested == "auto" and torch.cuda.is_available()) else "cpu"
        dtype = torch.bfloat16 if self.device == "cuda" and torch.cuda.is_bf16_supported() else torch.float32
        self.compute_type = str(dtype).removeprefix("torch.")

        self.tokenizer = AutoTokenizer.from_pretrained(
            str(self.model_path),
            local_files_only=True,
            **self.tokenizer_kwargs(),
        )
        self.transformer = AutoModelForCausalLM.from_pretrained(
            str(self.model_path),
            local_files_only=True,
            dtype=dtype,
            low_cpu_mem_usage=True,
        )
        self.transformer.to(self.device)
        self.transformer.eval()
        if self.device == "cuda":
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()

    def messages(self, text: str) -> list[dict[str, str]]:
        raise NotImplementedError

    def _generation(self) -> dict[str, Any]:
        return dict(self.model["generation"])

    def synchronize(self) -> None:
        if self.device == "cuda":
            self.torch.cuda.synchronize()

    def translate(self, text: str) -> str:
        torch = self.torch
        # Sampling profiles are made repeatable per source so latency repeats do
        # not silently become multiple quality trials.
        seed = int(
            fingerprint({"model": self.model_id, "source": text, "seed": self.generation_seed})[:8],
            16,
        )
        random.seed(seed)
        torch.manual_seed(seed)
        if self.device == "cuda":
            torch.cuda.manual_seed_all(seed)

        input_ids = self.tokenizer.apply_chat_template(
            self.messages(text),
            tokenize=True,
            add_generation_prompt=self.add_generation_prompt,
            return_tensors="pt",
        ).to(self.device)
        generation = self._generation()
        generation.setdefault("pad_token_id", self.tokenizer.eos_token_id)
        with torch.inference_mode():
            outputs = self.transformer.generate(
                input_ids,
                attention_mask=torch.ones_like(input_ids),
                **generation,
            )
        generated = outputs[0, input_ids.shape[-1] :]
        return normalize_display_output(self.tokenizer.decode(generated, skip_special_tokens=True))

    def metadata(self) -> dict[str, Any]:
        value = super().metadata()
        value["tokenizer_options"] = self.tokenizer_kwargs()
        if self.device == "cuda":
            value["peak_cuda_memory_bytes"] = self.torch.cuda.max_memory_allocated()
            value["cuda_device"] = self.torch.cuda.get_device_name()
        return value


class LFM2Adapter(TransformersAdapter):
    prompt_contract = 'system "Translate to English." plus one user turn; repository chat template'

    def messages(self, text: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": "Translate to English."},
            {"role": "user", "content": text},
        ]


class HYMTAdapter(TransformersAdapter):
    prompt_contract = (
        'single user turn: "Translate the following segment into English, without additional explanation."'
    )
    add_generation_prompt = False

    def messages(self, text: str) -> list[dict[str, str]]:
        return [
            {
                "role": "user",
                "content": "Translate the following segment into English, without additional explanation.\n\n" + text,
            }
        ]


class RivaAdapter(TransformersAdapter):
    prompt_contract = 'system language pair "ja-en" plus one user turn; repository chat template'

    def messages(self, text: str) -> list[dict[str, str]]:
        return [{"role": "system", "content": "ja-en"}, {"role": "user", "content": text}]

    def tokenizer_kwargs(self) -> dict[str, Any]:
        # Transformers detects the legacy Mistral tokenizer regex in this
        # checkpoint and explicitly recommends enabling its compatibility fix.
        return {"fix_mistral_regex": True}


class TranslateGemmaAdapter(TransformersAdapter):
    prompt_contract = "TranslateGemma typed text turn with source_lang_code=ja and target_lang_code=en"

    def load(self) -> None:
        try:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor
        except ImportError as exc:
            raise BenchmarkError("TranslateGemma requires a transformers release with Gemma 3 support") from exc

        self.torch = torch
        self.model_path = _download_snapshot(self.model)
        requested = self.device_preference
        if requested not in {"auto", "cuda", "cpu"}:
            raise BenchmarkError(f"Invalid device: {requested}")
        if requested == "cuda" and not torch.cuda.is_available():
            raise BenchmarkError("CUDA was requested but torch.cuda.is_available() is false")
        self.device = "cuda" if requested == "cuda" or (requested == "auto" and torch.cuda.is_available()) else "cpu"
        dtype = torch.bfloat16 if self.device == "cuda" and torch.cuda.is_bf16_supported() else torch.float32
        self.compute_type = str(dtype).removeprefix("torch.")
        self.processor = AutoProcessor.from_pretrained(str(self.model_path), local_files_only=True)
        self.transformer = AutoModelForImageTextToText.from_pretrained(
            str(self.model_path),
            local_files_only=True,
            dtype=dtype,
            low_cpu_mem_usage=True,
        ).to(self.device)
        self.transformer.eval()
        if self.device == "cuda":
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()

    def translate(self, text: str) -> str:
        torch = self.torch
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "source_lang_code": "ja",
                        "target_lang_code": "en",
                        "text": text,
                    }
                ],
            }
        ]
        inputs = self.processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self.device)
        with torch.inference_mode():
            outputs = self.transformer.generate(**inputs, **self.model["generation"])
        generated = outputs[0, inputs["input_ids"].shape[-1] :]
        return normalize_display_output(self.processor.decode(generated, skip_special_tokens=True))

    def metadata(self) -> dict[str, Any]:
        value = BaseAdapter.metadata(self)
        if self.device == "cuda":
            value["peak_cuda_memory_bytes"] = self.torch.cuda.max_memory_allocated()
            value["cuda_device"] = self.torch.cuda.get_device_name()
        return value


ADAPTERS = {
    "production": ProductionAdapter,
    "quickmt": QuickMTAdapter,
    "lfm2": LFM2Adapter,
    "hy_mt": HYMTAdapter,
    "riva": RivaAdapter,
    "translategemma": TranslateGemmaAdapter,
}


def create_adapter(
    model_id: str,
    model: dict[str, Any],
    repo_root: Path,
    device: str = "auto",
    generation_seed: int = 1729,
) -> BaseAdapter:
    adapter_name = model.get("adapter")
    adapter_class = ADAPTERS.get(adapter_name)
    if adapter_class is None:
        raise BenchmarkError(f"Unknown model adapter: {adapter_name}")
    return adapter_class(model_id, model, repo_root, device, generation_seed)


def environment_package_versions(model: dict[str, Any]) -> dict[str, str | None]:
    names = {requirement.split("==", 1)[0] for requirement in model.get("packages", [])}
    names.update({"ctranslate2", "sentencepiece", "huggingface-hub", "torch", "transformers"})
    return {name: _package_version(name) for name in sorted(names)}
