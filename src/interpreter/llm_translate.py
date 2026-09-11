"""Translation backend for Ollama and OpenAI-compatible chat endpoints.

Users bring their own model runtime (Ollama, LM Studio, llama.cpp server, vLLM,
a hosted API...). The application only needs a small HTTP client and a prompt.
"""

import re
import time
from collections import deque

import requests

from . import log
from .config import LLM_PROVIDERS, LLMSettings
from .models import ModelLoadError
from .translate import (
    DEFAULT_CACHE_SIZE,
    DEFAULT_SIMILARITY_THRESHOLD,
    TranslationCache,
    normalize_output,
)

logger = log.get_logger()

PROVIDER_OLLAMA = "ollama"
PROVIDER_OPENAI = "openai"
PROVIDERS = LLM_PROVIDERS
assert PROVIDERS == (PROVIDER_OLLAMA, PROVIDER_OPENAI)
PROVIDER_LABELS = {
    PROVIDER_OLLAMA: "Ollama",
    PROVIDER_OPENAI: "OpenAI-compatible",
}

# On Windows, "localhost" resolves to ::1 first and the IPv4 fallback costs ~2 s per
# request against a server that only listens on 127.0.0.1. Always default to the IP.
DEFAULT_BASE_URLS = {
    PROVIDER_OLLAMA: "http://127.0.0.1:11434",
    PROVIDER_OPENAI: "http://127.0.0.1:1234/v1",  # LM Studio's default port
}

DEFAULT_SYSTEM_PROMPT = (
    "You translate text captured by OCR from a Japanese retro video game. "
    "Translate the user's message from Japanese into {target_language}. "
    "Keep character names as they appear, keep menu items in the same order, "
    "and do not add explanations, notes, romaji or quotation marks. "
    "Output only the translation."
)

# Decoding settings shared by both providers: deterministic and bounded.
TEMPERATURE = 0
SEED = 42
MAX_OUTPUT_TOKENS = 256

# Keep the model resident between dialogue boxes; Ollama's default is 5 minutes.
OLLAMA_KEEP_ALIVE = "30m"

# Minimum timeout for the warm-up request, during which the server loads the model.
LOAD_TIMEOUT = 120.0

# Sent once at load time so the first real line does not pay the model load cost.
WARMUP_TEXT = "こんにちは"

# Sample used by the Settings "Test" button.
TEST_TEXT = "はじめまして。わたしはユウキです。"

# Some OpenAI-compatible servers return the reasoning inline instead of in a separate field.
THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class LLMTranslationError(Exception):
    """Raised when a translation request fails after the backend was loaded."""


def provider_label(provider: str) -> str:
    """Human-readable provider name for status displays."""
    return PROVIDER_LABELS.get(provider, provider)


def normalize_base_url(provider: str, base_url: str) -> str:
    """Normalize a user-entered base URL for the given provider.

    Ollama's native API lives at the server root, while OpenAI-compatible servers
    expose their routes under ``/v1``. Users paste either form, so accept both.
    """
    if provider not in DEFAULT_BASE_URLS:
        raise ValueError(f"Unsupported LLM provider '{provider}'. Use one of: {', '.join(PROVIDERS)}.")
    url = ((base_url or "").strip() or DEFAULT_BASE_URLS[provider]).rstrip("/")
    if provider == PROVIDER_OLLAMA:
        if url.endswith("/v1"):
            url = url[: -len("/v1")]
        return url
    if not url.endswith("/v1"):
        url += "/v1"
    return url


def describe_request_error(error: Exception, settings: LLMSettings) -> str:
    """Turn a requests exception into a message a user can act on."""
    label = provider_label(settings.provider)
    url = normalize_base_url(settings.provider, settings.base_url)

    if isinstance(error, requests.ConnectionError):
        hint = " Start it with 'ollama serve' or open the Ollama app." if settings.provider == PROVIDER_OLLAMA else ""
        return f"Cannot reach {label} at {url}.{hint}"
    if isinstance(error, requests.Timeout):
        return f"{label} at {url} did not answer within {settings.timeout:.0f}s."
    if isinstance(error, requests.HTTPError) and error.response is not None:
        status = error.response.status_code
        if status == 404:
            hint = f" Run 'ollama pull {settings.model}'." if settings.provider == PROVIDER_OLLAMA else ""
            return f"Model '{settings.model}' was not found on {label}.{hint}"
        if status in (401, 403):
            return f"{label} rejected the request (HTTP {status}). Check the API key."
        detail = _error_detail(error.response)
        return f"{label} returned HTTP {status}: {detail}" if detail else f"{label} returned HTTP {status}."
    return f"{label} request failed: {error}"


def _error_detail(response: requests.Response) -> str:
    """Extract the error message from an Ollama or OpenAI style error body."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:200]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message", ""))[:200]
    if isinstance(error, str):
        return error[:200]
    return ""


def list_models(settings: LLMSettings) -> list[str]:
    """List the models the endpoint offers.

    Raises:
        requests.RequestException: If the server cannot be reached or rejects the request.
    """
    base = normalize_base_url(settings.provider, settings.base_url)
    headers = _auth_headers(settings)
    if settings.provider == PROVIDER_OLLAMA:
        response = requests.get(f"{base}/api/tags", headers=headers, timeout=settings.timeout)
        response.raise_for_status()
        names = [m.get("name", "") for m in response.json().get("models", [])]
    else:
        response = requests.get(f"{base}/models", headers=headers, timeout=settings.timeout)
        response.raise_for_status()
        names = [m.get("id", "") for m in response.json().get("data", [])]
    return sorted(n for n in names if n)


def _auth_headers(settings: LLMSettings) -> dict[str, str]:
    if settings.api_key:
        return {"Authorization": f"Bearer {settings.api_key}"}
    return {}


def clean_output(raw: str) -> str:
    """Strip reasoning blocks, wrapping quotes and odd Unicode from a model reply."""
    text = THINK_BLOCK_RE.sub("", raw or "").strip()
    # Models sometimes quote the whole translation; drop a single outer pair.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'" and text[0] not in text[1:-1]:
        text = text[1:-1].strip()
    return normalize_output(text)


class LLMTranslator:
    """Translates Japanese text with a chat model behind an HTTP endpoint.

    Satisfies the same interface as translate.Translator so the worker can use
    either interchangeably. Recent (source, translation) pairs are replayed as prior
    conversation turns so the model keeps names and tone consistent across lines.
    """

    def __init__(
        self,
        settings: LLMSettings,
        cache_size: int = DEFAULT_CACHE_SIZE,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ):
        if settings.provider not in PROVIDERS:
            raise ModelLoadError(f"Unsupported LLM provider '{settings.provider}'. Use one of: {', '.join(PROVIDERS)}.")
        if not settings.timeout > 0:
            raise ModelLoadError(f"LLM timeout must be a positive number of seconds, got {settings.timeout!r}.")
        self._settings = settings
        self._cache = TranslationCache(cache_size, similarity_threshold)
        self._history: deque[tuple[str, str]] = deque(maxlen=max(0, settings.context_lines))
        self._session = requests.Session()
        self._loaded = False

    @property
    def name(self) -> str:
        """Short description for the status panel."""
        return f"{provider_label(self._settings.provider)} · {self._settings.model or 'no model'}"

    @property
    def system_prompt(self) -> str:
        template = self._settings.system_prompt or DEFAULT_SYSTEM_PROMPT
        return template.replace("{target_language}", self._settings.target_language or "English")

    def load(self) -> None:
        """Validate the endpoint with a warm-up request.

        The warm-up also makes the server load the model, so the first real line
        does not pay that cost.

        Raises:
            ModelLoadError: If the endpoint is unreachable, the model is missing, or auth fails.
        """
        if self._loaded:
            return
        if not self._settings.model:
            raise ModelLoadError("No translation model selected. Pick one in the Translation settings.")

        logger.info(
            "connecting to translation endpoint",
            provider=self._settings.provider,
            url=normalize_base_url(self._settings.provider, self._settings.base_url),
            model=self._settings.model,
        )
        start = time.perf_counter()
        try:
            # The server loads the model on this first request, which can take far longer
            # than a normal translation (several GB read from disk), so allow extra time.
            self._chat(self._build_messages(WARMUP_TEXT), timeout=max(self._settings.timeout, LOAD_TIMEOUT))
        except requests.RequestException as e:
            raise ModelLoadError(describe_request_error(e, self._settings)) from e
        self._loaded = True
        logger.info(
            "translation endpoint ready",
            model=self._settings.model,
            warmup_ms=int((time.perf_counter() - start) * 1000),
        )

    def is_loaded(self) -> bool:
        return self._loaded

    def translate(self, text: str) -> tuple[str, bool]:
        """Translate Japanese text.

        Returns:
            Tuple of (translated text, was_cached).

        Raises:
            LLMTranslationError: If the request fails.
        """
        if not text or not text.strip():
            return "", False

        cached = self._cache.get(text)
        if cached is not None:
            return cached, True

        if not self._loaded:
            self.load()

        try:
            raw = self._chat(self._build_messages(text))
        except requests.RequestException as e:
            raise LLMTranslationError(describe_request_error(e, self._settings)) from e

        result = clean_output(raw)
        if not result:
            logger.warning("empty translation from endpoint", text=text[:50])
            return "", False

        self._cache.put(text, result)
        self._history.append((text, result))
        return result, False

    def _build_messages(self, text: str) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": self.system_prompt}]
        for source, translation in self._history:
            messages.append({"role": "user", "content": source})
            messages.append({"role": "assistant", "content": translation})
        messages.append({"role": "user", "content": text})
        return messages

    def _chat(self, messages: list[dict[str, str]], timeout: float | None = None) -> str:
        timeout = self._settings.timeout if timeout is None else timeout
        if self._settings.provider == PROVIDER_OLLAMA:
            return self._chat_ollama(messages, timeout)
        return self._chat_openai(messages, timeout)

    def _chat_ollama(self, messages: list[dict[str, str]], timeout: float) -> str:
        base = normalize_base_url(PROVIDER_OLLAMA, self._settings.base_url)
        payload = {
            "model": self._settings.model,
            "messages": messages,
            "stream": False,
            # Reasoning models would otherwise spend seconds thinking about a menu item.
            # Ollama accepts the flag on models without a thinking mode too.
            "think": False,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {"temperature": TEMPERATURE, "seed": SEED, "num_predict": MAX_OUTPUT_TOKENS},
        }
        response = self._session.post(
            f"{base}/api/chat",
            json=payload,
            headers=_auth_headers(self._settings),
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content") or ""

    def _chat_openai(self, messages: list[dict[str, str]], timeout: float) -> str:
        base = normalize_base_url(PROVIDER_OPENAI, self._settings.base_url)
        payload = {
            "model": self._settings.model,
            "messages": messages,
            "stream": False,
            "temperature": TEMPERATURE,
            "seed": SEED,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }
        response = self._session.post(
            f"{base}/chat/completions",
            json=payload,
            headers=_auth_headers(self._settings),
            timeout=timeout,
        )
        response.raise_for_status()
        choices = response.json().get("choices") or []
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content") or ""


def check_endpoint(settings: LLMSettings) -> tuple[str, int]:
    """Load the endpoint and translate a sample line, for the Settings "Test" button.

    Returns:
        Tuple of (translation, round-trip milliseconds for the sample line).

    Raises:
        ModelLoadError: If the endpoint cannot be used.
        LLMTranslationError: If the sample translation fails.
    """
    translator = LLMTranslator(settings, cache_size=1)
    translator.load()
    start = time.perf_counter()
    translation, _ = translator.translate(TEST_TEXT)
    return translation, int((time.perf_counter() - start) * 1000)
