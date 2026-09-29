"""Bounded public-page reads, with DNS pinning and a check on every redirect."""

import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

USER_AGENT = "AIBusinessGurusResearch/1.0 (+https://aibiz.guru)"


class SiteError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def safe_url(value):
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 80, 443}
            or len(value) > 2048
            or any(ord(c) < 32 for c in value)
            or "\\" in value
        ):
            return ""
        host = parsed.hostname.encode("idna").decode()
        if host.lower().rstrip(".") in {
            "localhost",
            "metadata.google.internal",
        } or host.endswith((".localhost", ".local", ".internal")):
            return ""
        host = f"[{host}]" if ":" in host else host
        netloc = host + (f":{parsed.port}" if parsed.port else "")
        return urlunsplit(
            (
                parsed.scheme,
                netloc,
                quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~"),
                quote(parsed.query, safe="%=&?/:@!$'()*+,;-._~"),
                "",
            )
        )
    except (ValueError, UnicodeError):
        return ""


def public_address(host, port):
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        ips = [entry[4][0] for entry in addresses]
        if not ips:
            raise ValueError()
        for raw in ips:
            ip = ipaddress.ip_address(raw)
            if (
                not ip.is_global
                or ip.is_multicast
                or ip.is_reserved
                or (ip.version == 6 and (ip.ipv4_mapped or ip.sixtofour or ip.teredo))
            ):
                raise ValueError()
        return ips[0]
    except (ValueError, OSError):
        raise SiteError(
            "The website did not resolve to a reachable public address."
        ) from None


def fetch_page(url, *, deadline, plain=False, allowed_origin=None):
    for _ in range(4):
        url = safe_url(url)
        if not url:
            raise SiteError(
                "Only public HTTP or HTTPS websites on standard ports can be researched."
            )
        parsed = urlsplit(url)
        if allowed_origin and (parsed.scheme, parsed.netloc) != allowed_origin:
            raise SiteError(
                "An additional page redirected off this website and was skipped."
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SiteError("The website took too long to respond. Try again later.")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        ip = public_address(parsed.hostname, port)
        timeout = max(0.1, min(5, deadline - time.monotonic()))
        connection = http.client.HTTPConnection(parsed.hostname, port, timeout=timeout)
        response = None
        try:
            # Connect to the validated numeric address, retaining the original Host and TLS identity.
            sock = socket.create_connection((ip, port), timeout=timeout)
            connection.sock = sock
            if parsed.scheme == "https":
                context = ssl.create_default_context()
                connection.sock = context.wrap_socket(
                    sock, server_hostname=parsed.hostname
                )
            connection.request(
                "GET",
                parsed.path + ("?" + parsed.query if parsed.query else ""),
                headers={
                    "Host": parsed.netloc,
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                target = response.getheader("Location")
                if not target:
                    raise SiteError("The website returned an incomplete redirect.")
                url = urljoin(url, target)
                continue
            if response.status != 200:
                raise SiteError(
                    f"The website returned HTTP {response.status}. It may restrict automated access.",
                    status=response.status,
                )
            content_type = response.getheader("Content-Type", "").lower()
            allowed = (
                ("text/plain", "text/html")
                if plain
                else ("text/html", "application/xhtml+xml")
            )
            if not any(kind in content_type for kind in allowed):
                raise SiteError("This URL did not return a readable web page.")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise SiteError(
                    "This website requires an unsupported compressed response."
                )
            data = bytearray()
            limit = 256_000 if plain else 1_000_000
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SiteError("The website scan reached its time limit.")
                if connection.sock:
                    connection.sock.settimeout(min(5, remaining))
                chunk = response.read1(min(65536, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > limit:
                    raise SiteError("This page is too large for a quick scan.")
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                return url, data.decode(charset, errors="replace")
            except LookupError:
                return url, data.decode("utf-8", errors="replace")
        except (OSError, http.client.HTTPException, ValueError):
            raise SiteError(
                "The website could not be read securely or did not respond in time."
            ) from None
        finally:
            if response is not None:
                response.close()
            connection.close()
    raise SiteError("The website redirected too many times.")
