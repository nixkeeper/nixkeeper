"""Fetch URLs with retries, for the sources that need nothing more.

Repology has its own fetching (repology.py), as it also falls back between
domains. Safe mode, for the community's update checks, only fetches https
pages at public addresses, of at most MAX_BYTES.
"""

import email.utils
import gzip
import http.client
import ipaddress
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from .. import config, log

# The most a page may be in safe mode (the community's update checks).
MAX_BYTES = 2_000_000


class UnsafeURL(urllib.error.URLError):
    """A URL safe mode won't fetch: not https, or not a public address."""


def check_public(url):
    """Raise UnsafeURL unless url is safe to fetch.

    It is when it's https and its host resolves only to public internet
    addresses: not this machine, a private network, or a cloud metadata
    service.

    Raises:
        UnsafeURL: It isn't.
        urllib.error.URLError: The host can't be resolved.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise UnsafeURL(f"not an https URL: {url}")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443)
    except OSError as e:
        raise urllib.error.URLError(e) from e
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not address.is_global:
            raise UnsafeURL(f"{parts.hostname} is at a non-public address ({address})")


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect handler that follows only to URLs check_public accepts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Check newurl before following the redirect."""
        check_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# What safe mode fetches with.
_safe_opener = urllib.request.build_opener(_CheckedRedirects)


def asked_wait(err, now=None):
    """Return the seconds a server asked to wait before trying again, or None.

    That's the Retry-After of a 429 (too many requests) or 503
    (unavailable) answer, in seconds or as a date. None when it didn't say.
    """
    if not isinstance(err, urllib.error.HTTPError) or err.code not in (429, 503):
        return None
    value = (err.headers or {}).get("Retry-After", "").strip()
    if value.isdigit():
        return int(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0, round((when - (now or datetime.now(UTC))).total_seconds()))


def retry_wait(planned, err, host):
    """Return how long to wait before retrying after err.

    That's the planned delay, or longer when the server asked (asked_wait).

    Raises:
        urllib.error.HTTPError: err itself, when the server asked for more
            than MAX_RETRY_AFTER: that request fails, rather than stalling
            the whole run.
    """
    asked = asked_wait(err)
    if asked is None:
        return planned
    if asked > config.MAX_RETRY_AFTER:
        log.info(
            f"  {host} asks to wait {asked}s, longer than nixkeeper waits "
            f"({config.MAX_RETRY_AFTER}s): giving this request up"
        )
        raise err
    return max(planned, asked)


def get(url, accept=None, safe=False, compressed=False):
    """Return url's body as text, or None on a 404.

    The request is retried after RETRY_DELAYS seconds. It raises once every
    attempt has failed, or at once when the server asks to wait longer than
    MAX_RETRY_AFTER (retry_wait).

    Args:
        url: The URL.
        accept: The Accept header to send, if any.
        safe: Safe mode, for the community's update checks: https to public
            addresses only, redirects included, and at most MAX_BYTES.
            UnsafeURL is raised at once, not retried.
        compressed: Accept a gzipped answer, for big pages from sources
            nixkeeper trusts (not with safe: MAX_BYTES couldn't hold for
            what it unpacks to).
    """
    return _fetch(url, accept, safe, compressed)[0]


def get_bytes(url):
    """Return url's body as bytes, or None on a 404.

    That's for files such as compressed digests. The request is retried as
    get's is, with longer to arrive (DOWNLOAD_DEADLINE_SECONDS).
    """
    return _fetch(url, raw=True)[0]


def _read(resp, deadline, limit=None):
    """Read resp's body as it arrives.

    Args:
        resp: The response.
        deadline: The time.monotonic() past which reading stops with a
            TimeoutError, however steadily the body trickles in.
        limit: The most bytes wanted: at most limit + 1 are read, to tell
            that the body is over it.
    """
    if not isinstance(resp, http.client.HTTPResponse):
        # Not from a socket (a test's): nothing to wait for.
        return resp.read() if limit is None else resp.read(limit + 1)
    chunks, size = [], 0
    while limit is None or size <= limit:
        if time.monotonic() > deadline:
            raise TimeoutError("the answer took too long to arrive")
        want = 65536 if limit is None else min(65536, limit + 1 - size)
        chunk = resp.read1(want)  # what has arrived, without waiting for more
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


# What get_page returns when the server says the page hasn't changed since
# it was last read (HTTP 304).
NOT_MODIFIED = 304


# When each site was last asked, for pace().
_last_asked: dict[str, float] = {}
_pacing = threading.Lock()


def pace(url):
    """Wait so url's site is asked at most once every SITE_PAUSE_SECONDS.

    Update checks can have many pages on one site (PyPI, a vendor's), and
    they shouldn't arrive back to back. A site is a URL's host.
    """
    host = urllib.parse.urlsplit(url).netloc.lower()
    with _pacing:
        wait = _last_asked.get(host, float("-inf")) + config.SITE_PAUSE_SECONDS
        wait -= time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_asked[host] = time.monotonic()


def get_page(url, cached=None, safe=False):
    """Fetch a page read before, unless it hasn't changed since.

    What the server gave the last time lets it answer that the page hasn't
    changed, without sending it again. Otherwise this works as get does.

    Args:
        url: The URL.
        cached: {"etag", "lastModified"} from the last time, or None.
        safe: Safe mode, as get's.

    Returns:
        (text, cached). text is None on a 404, or NOT_MODIFIED when the page
        hasn't changed; cached is what to send next time ({} when the server
        gives neither).
    """
    pace(url)
    headers = {}
    if (cached or {}).get("etag"):
        headers["If-None-Match"] = cached["etag"]
    if (cached or {}).get("lastModified"):
        headers["If-Modified-Since"] = cached["lastModified"]
    text, answer = _fetch(url, safe=safe, extra=headers)
    if text is NOT_MODIFIED:
        return NOT_MODIFIED, dict(cached)
    found = {
        key: answer.get(header)
        for key, header in (("etag", "ETag"), ("lastModified", "Last-Modified"))
        if answer is not None and answer.get(header)
    }
    return text, found


def _fetch(url, accept=None, safe=False, compressed=False, extra=None, raw=False):
    """Fetch url as get does, also returning the answer's headers.

    Args:
        url: The URL.
        accept: The Accept header to send, if any.
        safe: Safe mode (get's).
        compressed: Accept a gzipped answer (get's).
        extra: More headers to send (get_page's).
        raw: Whether to return the body's bytes instead of text
            (get_bytes).

    Returns:
        (text, headers). text is None on a 404 (headers then None too), or
        NOT_MODIFIED when the server says the page hasn't changed (for
        get_page's extra headers).
    """
    headers = {"User-Agent": config.user_agent(), **(extra or {})}
    if accept:
        headers["Accept"] = accept
    if compressed and not safe:
        headers["Accept-Encoding"] = "gzip"
    host = urllib.parse.urlsplit(url).netloc
    allowed = config.DOWNLOAD_DEADLINE_SECONDS if raw else config.FETCH_DEADLINE_SECONDS
    last_err = None
    for attempt, delay in enumerate([0, *config.RETRY_DELAYS]):
        if attempt:
            delay = retry_wait(delay, last_err, host)
            log.info(f"  retrying in {delay}s...")
            time.sleep(delay)
        try:
            request = urllib.request.Request(url, headers=headers)
            if safe:
                check_public(url)
            open_url = _safe_opener.open if safe else urllib.request.urlopen
            deadline = time.monotonic() + allowed
            with open_url(request, timeout=20) as resp:
                if raw:
                    return _read(resp, deadline), resp.headers
                if not safe:
                    body = _read(resp, deadline)
                    if resp.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    return body.decode(errors="replace"), resp.headers
                body = _read(resp, deadline, MAX_BYTES)
                if len(body) > MAX_BYTES:
                    raise UnsafeURL(f"{host} answered more than {MAX_BYTES} bytes")
                return body.decode(errors="replace"), resp.headers
        except urllib.error.HTTPError as e:
            e.close()  # an HTTP error is also an open response
            if e.code == 404:
                return None, None
            if e.code == NOT_MODIFIED and extra:
                return NOT_MODIFIED, e.headers
            log.info(f"  {host} answered {e.code}")
            last_err = e
        except UnsafeURL:
            raise
        except (urllib.error.URLError, OSError) as e:
            log.info(f"  {host} request failed ({e})")
            last_err = e
    raise last_err
