import pytest

from app.browser_runtime import UnsafeBrowserTarget, validate_public_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://localhost",
        "http://10.0.0.2",
        "http://192.168.1.10",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://user:pass@example.com",
    ],
)
async def test_rejects_local_or_unsafe_urls(url):
    with pytest.raises(UnsafeBrowserTarget):
        await validate_public_url(url)


@pytest.mark.asyncio
async def test_accepts_public_https_url(monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        return [(None, None, None, None, ("93.184.216.34", 443))]

    monkeypatch.setattr("app.browser_runtime.socket.getaddrinfo", fake_getaddrinfo)
    assert await validate_public_url("https://example.com") == "https://example.com"


@pytest.mark.asyncio
async def test_rejects_hostname_with_private_dns_answer(monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        return [(None, None, None, None, ("10.0.0.8", 443))]

    monkeypatch.setattr("app.browser_runtime.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeBrowserTarget):
        await validate_public_url("https://example.com")
