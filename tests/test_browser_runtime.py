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
async def test_accepts_public_https_url():
    assert await validate_public_url("https://example.com") == "https://example.com"
