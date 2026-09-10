"""Tests for the LLM endpoint translation backend (no network access)."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from interpreter.config import Config, LLMSettings, TranslationBackend
from interpreter.llm_translate import (
    DEFAULT_SYSTEM_PROMPT,
    LLMTranslationError,
    LLMTranslator,
    check_endpoint,
    clean_output,
    describe_request_error,
    list_models,
    normalize_base_url,
)
from interpreter.models import ModelLoadError
from interpreter.translate import create_translator


def _response(payload: dict, status: int = 200) -> MagicMock:
    """Build a fake requests.Response."""
    response = MagicMock(spec=requests.Response)
    response.status_code = status
    response.json.return_value = payload
    response.text = json.dumps(payload)
    if status >= 400:
        error = requests.HTTPError(response=response)
        response.raise_for_status.side_effect = error
    else:
        response.raise_for_status.return_value = None
    return response


def _ollama_reply(content: str) -> dict:
    return {"model": "m", "message": {"role": "assistant", "content": content}, "done": True}


def _openai_reply(content: str | None) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class TestNormalizeBaseUrl:
    def test_ollama_strips_v1_and_trailing_slash(self):
        assert normalize_base_url("ollama", "http://127.0.0.1:11434/v1/") == "http://127.0.0.1:11434"

    def test_openai_appends_v1(self):
        assert normalize_base_url("openai", "https://api.openai.com") == "https://api.openai.com/v1"

    def test_openai_keeps_existing_v1(self):
        assert normalize_base_url("openai", "http://127.0.0.1:1234/v1") == "http://127.0.0.1:1234/v1"

    def test_empty_falls_back_to_provider_default(self):
        assert normalize_base_url("ollama", "") == "http://127.0.0.1:11434"
        assert normalize_base_url("openai", "  ") == "http://127.0.0.1:1234/v1"


class TestCleanOutput:
    def test_strips_think_block(self):
        assert clean_output("<think>\nhmm\n</think>\nHello there.") == "Hello there."

    def test_strips_outer_quotes_only_when_unambiguous(self):
        assert clean_output('"Hello there."') == "Hello there."
        # Inner quotes mean the outer pair is part of the dialogue, keep it
        assert clean_output('"Hi," she said, "bye."') == '"Hi," she said, "bye."'

    def test_normalizes_unicode_punctuation(self):
        assert clean_output("“Hi” — ok…") == '"Hi" -- ok...'

    def test_none_and_empty(self):
        assert clean_output(None) == ""
        assert clean_output("   ") == ""


class TestDescribeRequestError:
    def test_connection_error_mentions_url_and_ollama_hint(self):
        settings = LLMSettings(provider="ollama", base_url="http://127.0.0.1:11434")
        message = describe_request_error(requests.ConnectionError("boom"), settings)
        assert "Cannot reach Ollama at http://127.0.0.1:11434" in message
        assert "ollama serve" in message

    def test_timeout(self):
        settings = LLMSettings(provider="openai", base_url="http://127.0.0.1:1234", timeout=12)
        message = describe_request_error(requests.Timeout(), settings)
        assert "did not answer within 12s" in message

    def test_404_suggests_pull_for_ollama(self):
        settings = LLMSettings(provider="ollama", model="gemma3:4b")
        error = requests.HTTPError(response=_response({"error": "model 'gemma3:4b' not found"}, 404))
        message = describe_request_error(error, settings)
        assert "gemma3:4b" in message
        assert "ollama pull gemma3:4b" in message

    def test_401_points_at_api_key(self):
        settings = LLMSettings(provider="openai")
        error = requests.HTTPError(response=_response({"error": {"message": "bad key"}}, 401))
        assert "API key" in describe_request_error(error, settings)

    def test_other_http_error_includes_server_detail(self):
        settings = LLMSettings(provider="openai")
        error = requests.HTTPError(response=_response({"error": {"message": "context too long"}}, 400))
        message = describe_request_error(error, settings)
        assert "HTTP 400" in message
        assert "context too long" in message


class TestListModels:
    def test_ollama_uses_tags_endpoint(self):
        settings = LLMSettings(provider="ollama", base_url="http://127.0.0.1:11434")
        payload = {"models": [{"name": "qwen3:0.6b"}, {"name": "gemma3:4b"}]}
        with patch("interpreter.llm_translate.requests.get", return_value=_response(payload)) as get:
            assert list_models(settings) == ["gemma3:4b", "qwen3:0.6b"]
        assert get.call_args.args[0] == "http://127.0.0.1:11434/api/tags"
        assert "Authorization" not in get.call_args.kwargs["headers"]

    def test_openai_uses_models_endpoint_with_bearer(self):
        settings = LLMSettings(provider="openai", base_url="https://api.example.com", api_key="sk-test")
        payload = {"data": [{"id": "gpt-x"}, {"id": "gpt-a"}]}
        with patch("interpreter.llm_translate.requests.get", return_value=_response(payload)) as get:
            assert list_models(settings) == ["gpt-a", "gpt-x"]
        assert get.call_args.args[0] == "https://api.example.com/v1/models"
        assert get.call_args.kwargs["headers"] == {"Authorization": "Bearer sk-test"}


class TestLLMTranslator:
    def _translator(self, **overrides) -> tuple[LLMTranslator, MagicMock]:
        settings = LLMSettings(provider="ollama", model="qwen3:0.6b", **overrides)
        translator = LLMTranslator(settings)
        post = MagicMock()
        translator._session.post = post
        return translator, post

    def test_name(self):
        translator, _ = self._translator()
        assert translator.name == "Ollama · qwen3:0.6b"

    def test_load_requires_model(self):
        translator = LLMTranslator(LLMSettings(provider="ollama", model=""))
        with pytest.raises(ModelLoadError, match="No translation model selected"):
            translator.load()

    def test_load_sends_warmup_with_ollama_payload(self):
        translator, post = self._translator()
        post.return_value = _response(_ollama_reply("Hello"))

        translator.load()

        assert translator.is_loaded()
        url = post.call_args.args[0]
        payload = post.call_args.kwargs["json"]
        assert url == "http://127.0.0.1:11434/api/chat"
        assert payload["model"] == "qwen3:0.6b"
        assert payload["stream"] is False
        assert payload["think"] is False
        assert payload["options"]["temperature"] == 0
        assert payload["messages"][0]["role"] == "system"
        assert "into English" in payload["messages"][0]["content"]

    def test_load_maps_connection_error(self):
        translator, post = self._translator()
        post.side_effect = requests.ConnectionError("refused")
        with pytest.raises(ModelLoadError, match="Cannot reach Ollama"):
            translator.load()
        assert not translator.is_loaded()

    def test_load_maps_missing_model(self):
        translator, post = self._translator()
        post.return_value = _response({"error": "model 'qwen3:0.6b' not found"}, 404)
        with pytest.raises(ModelLoadError, match=r"ollama pull qwen3:0.6b"):
            translator.load()

    def test_translate_cleans_and_caches(self):
        translator, post = self._translator()
        translator._loaded = True
        post.return_value = _response(_ollama_reply('<think>x</think>"Hello, I’m Yuuki."'))

        result, cached = translator.translate("はじめまして。わたしはユウキです。")
        assert (result, cached) == ("Hello, I'm Yuuki.", False)

        # Second call is served by the fuzzy cache without a request
        result, cached = translator.translate("はじめまして。わたしはユウキです。")
        assert (result, cached) == ("Hello, I'm Yuuki.", True)
        assert post.call_count == 1

    def test_translate_replays_history_as_context(self):
        translator, post = self._translator(context_lines=2)
        translator._loaded = True
        post.side_effect = [
            _response(_ollama_reply("One")),
            _response(_ollama_reply("Two")),
            _response(_ollama_reply("Three")),
        ]

        translator.translate("いち")
        translator.translate("に")
        translator.translate("さん")

        messages = post.call_args.kwargs["json"]["messages"]
        roles = [m["role"] for m in messages]
        assert roles == ["system", "user", "assistant", "user", "assistant", "user"]
        assert [m["content"] for m in messages[1:]] == ["いち", "One", "に", "Two", "さん"]

    def test_translate_history_is_bounded(self):
        translator, post = self._translator(context_lines=1)
        translator._loaded = True
        post.side_effect = [_response(_ollama_reply(str(i))) for i in range(3)]

        for text in ("いち", "に", "さん"):
            translator.translate(text)

        messages = post.call_args.kwargs["json"]["messages"]
        assert [m["content"] for m in messages[1:]] == ["に", "1", "さん"]

    def test_translate_with_zero_context(self):
        translator, post = self._translator(context_lines=0)
        translator._loaded = True
        post.side_effect = [_response(_ollama_reply("One")), _response(_ollama_reply("Two"))]

        translator.translate("いち")
        translator.translate("に")

        messages = post.call_args.kwargs["json"]["messages"]
        assert [m["role"] for m in messages] == ["system", "user"]

    def test_translate_empty_reply_is_not_cached(self):
        translator, post = self._translator()
        translator._loaded = True
        post.return_value = _response(_ollama_reply("   "))

        assert translator.translate("いち") == ("", False)
        translator.translate("いち")
        assert post.call_count == 2

    def test_translate_request_failure_raises_translation_error(self):
        translator, post = self._translator()
        translator._loaded = True
        post.side_effect = requests.Timeout()
        with pytest.raises(LLMTranslationError, match="did not answer"):
            translator.translate("いち")

    def test_translate_blank_input(self):
        translator, post = self._translator()
        assert translator.translate("   ") == ("", False)
        post.assert_not_called()

    def test_custom_prompt_and_target_language(self):
        translator, post = self._translator(
            system_prompt="Translate to {target_language}. Be terse.",
            target_language="French",
        )
        translator._loaded = True
        post.return_value = _response(_ollama_reply("Bonjour"))

        translator.translate("こんにちは")

        assert post.call_args.kwargs["json"]["messages"][0]["content"] == "Translate to French. Be terse."

    def test_default_prompt_mentions_target_language(self):
        translator, _ = self._translator(target_language="German")
        assert "into German" in translator.system_prompt
        assert "{target_language}" not in translator.system_prompt
        assert "{target_language}" in DEFAULT_SYSTEM_PROMPT


class TestOpenAIProvider:
    def test_payload_shape_and_auth(self):
        settings = LLMSettings(provider="openai", base_url="http://127.0.0.1:1234", model="local", api_key="k")
        translator = LLMTranslator(settings)
        translator._loaded = True
        post = MagicMock(return_value=_response(_openai_reply("Hello")))
        translator._session.post = post

        assert translator.translate("こんにちは") == ("Hello", False)

        assert post.call_args.args[0] == "http://127.0.0.1:1234/v1/chat/completions"
        payload = post.call_args.kwargs["json"]
        assert payload["temperature"] == 0
        assert payload["max_tokens"] == 256
        assert "think" not in payload
        assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer k"}

    def test_null_content_is_empty(self):
        settings = LLMSettings(provider="openai", model="local")
        translator = LLMTranslator(settings)
        translator._loaded = True
        translator._session.post = MagicMock(return_value=_response(_openai_reply(None)))
        assert translator.translate("こんにちは") == ("", False)

    def test_no_choices_is_empty(self):
        settings = LLMSettings(provider="openai", model="local")
        translator = LLMTranslator(settings)
        translator._loaded = True
        translator._session.post = MagicMock(return_value=_response({"choices": []}))
        assert translator.translate("こんにちは") == ("", False)


class TestCheckEndpoint:
    def test_returns_translation_and_latency(self):
        settings = LLMSettings(provider="ollama", model="m")
        with patch.object(LLMTranslator, "_chat", return_value="Hello, I'm Yuuki."):
            translation, ms = check_endpoint(settings)
        assert translation == "Hello, I'm Yuuki."
        assert isinstance(ms, int)


class TestFactory:
    def test_default_is_sugoi(self):
        config = Config()
        assert create_translator(config).name == "Sugoi V4"

    def test_llm_backend_uses_settings(self):
        config = Config(translation_backend=TranslationBackend.LLM, llm=LLMSettings(model="gemma3:4b"))
        translator = create_translator(config)
        assert isinstance(translator, LLMTranslator)
        assert translator.name == "Ollama · gemma3:4b"


class TestConfigRoundTrip:
    def test_defaults_do_not_write_llm_block(self, tmp_path):
        path = tmp_path / "config.yml"
        Config().save(str(path))
        text = path.read_text(encoding="utf-8")
        assert "translation_backend: sugoi" in text
        assert "llm:" not in text

    def test_llm_settings_round_trip(self, tmp_path):
        path = tmp_path / "config.yml"
        config = Config(
            translation_backend=TranslationBackend.LLM,
            llm=LLMSettings(
                provider="openai",
                base_url="https://api.example.com/v1",
                model="gpt-x",
                api_key="sk",
                target_language="French",
                system_prompt="Custom {target_language}",
                context_lines=5,
                timeout=12.5,
            ),
        )
        config.save(str(path))

        loaded = Config.load(str(path))
        assert loaded.translation_backend == TranslationBackend.LLM
        assert loaded.llm == config.llm

    def test_default_prompt_is_not_persisted(self, tmp_path):
        path = tmp_path / "config.yml"
        Config(translation_backend=TranslationBackend.LLM, llm=LLMSettings(model="m")).save(str(path))
        assert "system_prompt" not in path.read_text(encoding="utf-8")
        assert Config.load(str(path)).llm.system_prompt is None

    def test_invalid_values_fall_back(self, tmp_path):
        path = tmp_path / "config.yml"
        path.write_text(
            "translation_backend: banana\nllm:\n  model: m\n  context_lines: many\n  timeout: 5\n  unknown: 1\n",
            encoding="utf-8",
        )
        loaded = Config.load(str(path))
        assert loaded.translation_backend == TranslationBackend.SUGOI
        assert loaded.llm.model == "m"
        assert loaded.llm.context_lines == 3
        assert loaded.llm.timeout == 5.0

    def test_missing_keys_use_defaults(self, tmp_path):
        path = tmp_path / "config.yml"
        path.write_text("window_title: x\n", encoding="utf-8")
        loaded = Config.load(str(path))
        assert loaded.translation_backend == TranslationBackend.SUGOI
        assert loaded.llm == LLMSettings()
