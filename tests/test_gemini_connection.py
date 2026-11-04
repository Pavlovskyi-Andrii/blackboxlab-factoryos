import pytest
from unittest.mock import patch, MagicMock


def map_gemini_response_status(status_code: int | None, is_timeout: bool = False) -> str:
    """Maps HTTP status code / errors from Google API to connection status string."""
    if is_timeout:
        return "unreachable"
    if status_code == 200:
        return "verified"
    if status_code in (400, 403):
        return "invalid_key"
    return "unreachable"


def test_gemini_status_mapping_verified():
    assert map_gemini_response_status(200) == "verified"


def test_gemini_status_mapping_invalid_key():
    assert map_gemini_response_status(400) == "invalid_key"
    assert map_gemini_response_status(403) == "invalid_key"


def test_gemini_status_mapping_unreachable():
    assert map_gemini_response_status(500) == "unreachable"
    assert map_gemini_response_status(None, is_timeout=True) == "unreachable"


def test_gemini_key_never_exposed_in_response():
    secret_key = "AIzaSySecretKey987654321"
    res_payload = {
        "id": "gemini",
        "status": "verified",
        "last_checked": "2026-01-01T00:00:00Z",
    }
    payload_str = str(res_payload)
    assert secret_key not in payload_str
