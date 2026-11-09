"""Offline checks for Remote Bob's API URL compatibility."""
import pytest

from runtime_config import api_url


@pytest.mark.parametrize(
    ("current", "legacy", "expected"),
    [
        (None, None, "http://localhost:8080"),
        ("http://remote-bob:8080", None, "http://remote-bob:8080"),
        (None, "http://legacy:8080", "http://legacy:8080"),
        ("http://remote-bob:8080", "http://legacy:8080", "http://remote-bob:8080"),
        ("", "http://legacy:8080", "http://legacy:8080"),
        ("", "", "http://localhost:8080"),
    ],
)
def test_api_url_precedence(monkeypatch, current, legacy, expected):
    for name, value in (("REMOTE_BOB_URL", current), ("HARNESS_URL", legacy)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert api_url() == expected
