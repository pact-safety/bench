"""Network-free regressions for user-controlled reading URLs."""

import asyncio
import socket
import ssl

import httpx
import pytest

from app.services import external_capture


HTML = b"<title>Reading</title><p>" + b"Research details. " * 30 + b"</p>"


@pytest.fixture
def network(monkeypatch):
    requests = []
    resolutions = []
    addresses = ["93.184.216.34"]
    responses = []

    async def resolve(self, host, port, **kwargs):
        resolutions.append(host)
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET,
                 socket.SOCK_STREAM, 6, "", (ip, port)) for ip in addresses]

    def respond(request):
        requests.append(request)
        if responses:
            return responses.pop(0)
        return httpx.Response(200, stream=Chunks([HTML]))

    real_client = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    # The old implementation must never make a real request in the red phase.
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("unsafe sync fetch"))
    return requests, resolutions, addresses, responses


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.org/a", "http://user:pass@example.org",
    "http://127.0.0.1/", "http://[::1]/", "http://[::ffff:127.0.0.1]/",
    "http://169.254.169.254/", "http://100.64.0.1/", "http://0.0.0.0/",
    "http://[fe80::1%25en0]/", "https://example.org/\nsecret",
])
def test_rejects_unsafe_urls_without_requests(network, url):
    assert asyncio.run(external_capture.fetch_body(url)) is None
    assert network[0] == []


@pytest.mark.parametrize("addresses", [
    ["127.0.0.1"], ["10.1.2.3"], ["::1"], ["fd00::1"],
    ["93.184.216.34", "192.168.1.1"], ["64:ff9b::a00:1"],
])
def test_rejects_any_nonpublic_dns_answer(network, addresses):
    network[2][:] = addresses
    assert asyncio.run(external_capture.fetch_body("https://example.org")) is None
    assert network[0] == []


@pytest.mark.parametrize("ip", ["93.184.216.34", "2606:4700:4700::1111"])
def test_pins_request_to_validated_ip_preserving_host_and_tls_name(network, ip):
    network[2][:] = [ip]
    result = asyncio.run(external_capture.fetch_body("https://example.org:8443/read?q=1"))
    assert result["page_title"] == "Reading"
    assert "Research details." in result["source_text"]
    request, = network[0]
    assert request.url.host == ip
    assert request.url.port == 8443
    assert request.url.raw_path == b"/read?q=1"
    assert request.headers["Host"] == "example.org:8443"
    assert request.extensions["sni_hostname"] == "example.org"
    assert network[1] == ["example.org"]


def test_redirect_to_private_address_is_rejected(network):
    network[3].append(httpx.Response(302, headers={"location": "http://127.0.0.1/"}))
    assert asyncio.run(external_capture.fetch_body("https://example.org")) is None
    assert len(network[0]) == 1


def test_relative_redirect_uses_original_hostname_and_revalidates_dns(network):
    network[3].append(httpx.Response(302, headers={"location": "/next"}))
    assert asyncio.run(external_capture.fetch_body("https://example.org/start")) is not None
    assert network[1] == ["example.org", "example.org"]
    assert [r.url.path for r in network[0]] == ["/start", "/next"]


def test_redirect_hostname_rebinding_is_rejected(network, monkeypatch):
    calls = []

    async def resolve(self, host, port, **kwargs):
        calls.append(host)
        ip = "93.184.216.34" if len(calls) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", resolve)
    network[3].append(httpx.Response(302, headers={"location": "/next"}))
    assert asyncio.run(external_capture.fetch_body("https://example.org/start")) is None
    assert calls == ["example.org", "example.org"]
    assert len(network[0]) == 1


def test_redirect_count_is_bounded(network):
    network[3][:] = [httpx.Response(302, headers={"location": "/again"}) for _ in range(20)]
    assert asyncio.run(external_capture.fetch_body("https://example.org")) is None
    assert len(network[0]) <= 6


@pytest.mark.parametrize("headers", [
    {"content-length": "999999999"}, {"content-encoding": "gzip"},
    {"content-type": "application/octet-stream"},
])
def test_rejects_oversized_or_unsupported_responses(network, headers):
    network[3].append(httpx.Response(200, headers=headers, stream=Chunks([HTML])))
    assert asyncio.run(external_capture.fetch_body("https://example.org")) is None


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.read_count = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk

    async def aclose(self):
        self.closed = True


def test_bounds_actual_stream_even_without_content_length(network, monkeypatch):
    monkeypatch.setattr(external_capture, "_MAX_RESPONSE_BYTES", 1000)
    stream = Chunks([b"x" * 600] * 10)
    network[3].append(httpx.Response(200, stream=stream))
    assert asyncio.run(external_capture.fetch_body("https://example.org")) is None
    assert stream.read_count == 2
    assert stream.closed


def test_total_deadline_includes_dns(network, monkeypatch):
    async def stalled_dns(*args, **kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", stalled_dns)

    async def run():
        return await asyncio.wait_for(
            external_capture.fetch_body("https://example.org", timeout=0.01), timeout=0.5,
        )

    assert asyncio.run(run()) is None
    assert network[0] == []


def test_total_deadline_interrupts_slow_body_and_closes_response(network):
    class Slow(Chunks):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.005)
                yield b"x"

    stream = Slow([])
    network[3].append(httpx.Response(200, stream=stream))

    async def run():
        return await asyncio.wait_for(
            external_capture.fetch_body("https://example.org", timeout=0.03), timeout=0.5,
        )

    assert asyncio.run(run()) is None
    assert stream.closed


def test_real_httpx_transport_connects_numeric_ip_and_verifies_original_tls_host(monkeypatch):
    from httpcore._backends.anyio import AnyIOBackend

    connected = []
    tls_names = []
    written = []

    class Wire:
        async def read(self, max_bytes, timeout=None):
            return (b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(HTML)).encode()
                    + b"\r\nConnection: close\r\n\r\n" + HTML)

        async def write(self, buffer, timeout=None):
            written.append(buffer)

        async def aclose(self):
            pass

        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            assert ssl_context.verify_mode == ssl.CERT_REQUIRED
            assert ssl_context.check_hostname
            tls_names.append(server_hostname)
            return self

        def get_extra_info(self, info):
            return None

    async def resolve(self, host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    async def connect(self, host, port, **kwargs):
        connected.append((host, port))
        return Wire()

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(AnyIOBackend, "connect_tcp", connect)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    result = asyncio.run(external_capture.fetch_body("https://example.org/read"))
    assert result["page_title"] == "Reading"
    assert connected == [("93.184.216.34", 443)]
    assert tls_names == ["example.org"]
    assert b"Host: example.org\r\n" in b"".join(written)
