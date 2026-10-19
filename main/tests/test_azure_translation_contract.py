"""Azure offline transport contract; never uses user credentials or network."""
import io
import json
import urllib.error

import pytest

from translation.models import TranslationErrorCode, TranslationRequest
from translation.providers.azure import AzureTranslateProvider


def test_request_response_language_and_region(monkeypatch):
    captured = {}

    def respond(request, timeout):
        captured.update(request=request, timeout=timeout)
        return io.BytesIO(json.dumps([{"detectedLanguage": {"language": "en"},
                                      "translations": [{"text": "合成测试"}]}]).encode())

    monkeypatch.setattr("urllib.request.urlopen", respond)
    result = AzureTranslateProvider({"api_key": "synthetic", "region": "eastasia"}).translate(
        TranslationRequest("Synthetic test", "zh-Hans", timeout=3))
    assert result.success and result.translated_text == "合成测试"
    assert result.detected_source_lang == "en"
    request = captured["request"]
    assert "to=zh-Hans" in request.full_url
    assert json.loads(request.data) == [{"Text": "Synthetic test"}]
    headers = {k.lower(): v for k, v in request.header_items()}
    assert headers["ocp-apim-subscription-region"] == "eastasia"
    assert captured["timeout"] == 3


@pytest.mark.parametrize("error,expected", [
    (TimeoutError(), TranslationErrorCode.NETWORK_ERROR),
    (urllib.error.URLError("synthetic offline"), TranslationErrorCode.NETWORK_ERROR),
    (urllib.error.HTTPError("https://example.invalid", 401, "Unauthorized", {}, None),
     TranslationErrorCode.AUTH_FAILED),
])
def test_error_contract(monkeypatch, error, expected):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr("urllib.request.urlopen", fail)
    result = AzureTranslateProvider({"api_key": "synthetic"}).translate(
        TranslationRequest("Synthetic test", "zh-Hans"))
    assert not result.success and result.error_code == expected


def test_empty_input_does_not_use_transport(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: pytest.fail("unexpected network"))
    result = AzureTranslateProvider({"api_key": "synthetic"}).translate(TranslationRequest(" ", "en"))
    assert result.error_code == TranslationErrorCode.INVALID_REQUEST
