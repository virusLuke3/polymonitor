from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlparse

from api.services.trusted_hls_sources import TRUSTED_HLS_SOURCES
from api.clients.source_transport import source_session, read_with_retry, read_response_bytes


DEFAULT_TIMEOUT_SECONDS = 12
MAX_MANIFEST_BYTES = 2_000_000
MAX_SEGMENT_BYTES = 16_000_000
M3U8_CONTENT_TYPES = (
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "audio/x-mpegurl",
)
URI_ATTR_RE = re.compile(r'URI="([^"]+)"')


@dataclass(frozen=True)
class TrustedHlsRule:
    url: str
    referer: str | None = None
    additional_paths: tuple[str, ...] = ()

    @property
    def parsed(self):
        return urlparse(self.url)


class HlsProxyError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _rules() -> list[TrustedHlsRule]:
    rules = []
    for source in TRUSTED_HLS_SOURCES:
        url = str(source.get("hlsUrl") or "").strip()
        if not url:
            continue
        rules.append(TrustedHlsRule(url=url, referer=str(source.get("hlsProxyReferer") or "").strip() or None,
                                   additional_paths=tuple(source.get("hlsProxyAdditionalPaths") or ())))
        for alternate in (source.get("hlsAlternates") or [])[:2]:
            alternate_url = str(alternate.get("url") or "").strip()
            if alternate_url.startswith("https://"):
                paths = tuple(path for path in alternate.get("additionalPaths", [])
                              if isinstance(path, str) and path.startswith("/") and path.endswith("/") and path != "/")
                rules.append(TrustedHlsRule(url=alternate_url, additional_paths=paths))
    return rules


def is_allowed_hls_url(url: str) -> bool:
    try:
        return select_rule(url) is not None
    except HlsProxyError:
        return False


def select_rule(url: str) -> TrustedHlsRule | None:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise HlsProxyError("only trusted https HLS URLs can be proxied", 400)
    normalized_host = parsed.netloc.lower()
    normalized_path = parsed.path or "/"
    for rule in _rules():
        base = rule.parsed
        if normalized_host != base.netloc.lower():
            continue
        base_path = base.path.rsplit("/", 1)[0].rstrip("/") + "/"
        if normalized_path == base.path or normalized_path.startswith(base_path):
            return rule
        if any(normalized_path.startswith(path) for path in rule.additional_paths):
            return rule
    raise HlsProxyError("HLS URL is not in the trusted playback allowlist", 403)


def _is_manifest_url(url: str, content_type: str = "") -> bool:
    lower_url = url.lower()
    lower_type = content_type.lower()
    return ".m3u8" in lower_url or any(value in lower_type for value in M3U8_CONTENT_TYPES)


def _headers_for(rule: TrustedHlsRule) -> dict[str, str]:
    headers = {
        "Accept": "*/*",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
    }
    if rule.referer:
        headers["Referer"] = rule.referer
        referer_parts = urlparse(rule.referer)
        if referer_parts.scheme and referer_parts.netloc:
            headers["Origin"] = f"{referer_parts.scheme}://{referer_parts.netloc}"
    return headers


def _proxy_uri(full_url: str) -> str:
    return f"hls-proxy?url={quote(full_url, safe='')}"


def rewrite_manifest(manifest: str, *, manifest_url: str) -> str:
    lines: list[str] = []
    for raw_line in str(manifest or "").splitlines():
        line = raw_line.strip()
        if not line:
            lines.append(raw_line)
            continue
        if line.startswith("#"):
            def replace_uri(match: re.Match[str]) -> str:
                return f'URI="{_proxy_uri(urljoin(manifest_url, match.group(1)))}"'

            lines.append(URI_ATTR_RE.sub(replace_uri, raw_line))
            continue
        lines.append(_proxy_uri(urljoin(manifest_url, line)))
    return "\n".join(lines) + "\n"


def fetch_hls_resource(url: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> tuple[bytes, str, int]:
    target = str(url or "").strip()
    deadline = time.monotonic() + timeout * 2 + 1
    # HLS providers use legitimate 307 media beacons. Every hop must remain in
    # explicitly configured broadcaster paths; never make this an open proxy.
    with source_session() as session:
        for hop in range(4):
            rule = select_rule(target)
            if rule is None:
                raise HlsProxyError("HLS URL is not in the trusted playback allowlist", 403)

            def read(response):
                if response.status_code in {301, 302, 303, 307, 308}:
                    return None, "", response.status_code, response.headers.get("Location")
                response.raise_for_status()
                if response.status_code != 200:
                    raise HlsProxyError(f"upstream returned HTTP {response.status_code}", 502)
                content_type = str(response.headers.get("Content-Type") or "")
                max_bytes = MAX_MANIFEST_BYTES if _is_manifest_url(target, content_type) else MAX_SEGMENT_BYTES
                data = read_response_bytes(response, max_bytes, deadline=deadline)
                return data, content_type, response.status_code, None

            data, content_type, status, redirect = read_with_retry(
                session, target, read, attempts=2, deadline=deadline,
                headers=_headers_for(rule), timeout=timeout, stream=True, allow_redirects=False,
            )
            if status in {301, 302, 303, 307, 308}:
                if not redirect or hop == 3:
                    raise HlsProxyError("HLS redirect limit or missing destination", 502)
                target = urljoin(target, redirect)
                select_rule(target)  # validate before the next network request
                continue
            if _is_manifest_url(target, content_type):
                rewritten = rewrite_manifest(data.decode("utf-8", errors="replace"), manifest_url=target)
                return rewritten.encode("utf-8"), "application/vnd.apple.mpegurl; charset=utf-8", status
            return data, content_type or "application/octet-stream", status
    raise HlsProxyError("HLS source unavailable", 502)


def cache_control_for(content_type: str) -> str:
    lower = str(content_type or "").lower()
    if "mpegurl" in lower:
        return "public, max-age=8, stale-while-revalidate=30"
    return "public, max-age=60"
