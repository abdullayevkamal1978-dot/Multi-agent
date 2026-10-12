"""ASGI gateway: serve the route manifest and proxy Streamlit HTTP/WebSockets."""
from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

UPSTREAM_HTTP = "http://127.0.0.1:8501"
UPSTREAM_WS = "ws://127.0.0.1:8501"
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host",
}
client = httpx.AsyncClient(follow_redirects=False, timeout=None)
manifest_path = Path(__file__).resolve().parents[1] / "public" / "manus-routes.json"


async def app(scope, receive, send):
    """Route one ASGI HTTP, WebSocket, or lifecycle event."""
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await client.aclose()
                await send({"type": "lifespan.shutdown.complete"})
                return
    elif scope["type"] == "http":
        if scope["path"] == "/manus-routes.json":
            body = manifest_path.read_bytes()
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-cache"),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return
        await _proxy_http(scope, receive, send)
    elif scope["type"] == "websocket":
        await _proxy_websocket(scope, receive, send)


async def _proxy_http(scope, receive, send):
    raw_path = quote(scope["path"], safe="/@:%!$&'()*+,;=-._~")
    query = scope.get("query_string", b"").decode("ascii")
    url = f"{UPSTREAM_HTTP}{raw_path}" + (f"?{query}" if query else "")
    body = bytearray()
    while True:
        event = await receive()
        if event["type"] == "http.disconnect":
            return
        body.extend(event.get("body", b""))
        if not event.get("more_body", False):
            break
    headers = []
    for key, value in scope.get("headers", []):
        name = key.decode("latin-1").lower()
        if name in HOP_BY_HOP or name in {"x-forwarded-host", "x-forwarded-proto"}:
            continue
        value_text = value.decode("latin-1")
        if name == "origin":
            value_text = "http://127.0.0.1:8501"
        headers.append((name, value_text))
    request = client.build_request(scope["method"], url, headers=headers, content=bytes(body))
    response = await client.send(request, stream=True)
    response_headers = [
        (key.lower(), value)
        for key, value in response.headers.raw
        if key.decode("latin-1").lower() not in HOP_BY_HOP
    ]
    await send({"type": "http.response.start", "status": response.status_code, "headers": response_headers})
    async for chunk in response.aiter_raw():
        await send({"type": "http.response.body", "body": chunk, "more_body": True})
    await send({"type": "http.response.body", "body": b""})
    await response.aclose()


async def _proxy_websocket(scope, receive, send):
    await receive()  # websocket.connect
    raw_path = quote(scope["path"], safe="/@:%!$&'()*+,;=-._~")
    query = scope.get("query_string", b"").decode("ascii")
    uri = f"{UPSTREAM_WS}{raw_path}" + (f"?{query}" if query else "")
    incoming_headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }
    origin = incoming_headers.get("origin")
    client_hosts = [
        value.split(",", 1)[0].strip()
        for value in (incoming_headers.get("x-forwarded-host"), incoming_headers.get("host"))
        if value
    ]
    if origin and client_hosts and not _origin_matches_hosts(origin, client_hosts):
        print(f"Rejected websocket origin mismatch: origin={origin!r}, hosts={client_hosts!r}", flush=True)
        await send({"type": "websocket.close", "code": 1008})
        return
    upstream_origin = "http://127.0.0.1:8501" if origin else None
    headers = [
        (key.decode("latin-1"), value.decode("latin-1"))
        for key, value in scope.get("headers", [])
        if key.decode("latin-1").lower() not in HOP_BY_HOP
        and key.decode("latin-1").lower() not in {"x-forwarded-host", "x-forwarded-proto"}
        and key.decode("latin-1").lower() not in {
            "origin", "sec-websocket-key", "sec-websocket-version",
            "sec-websocket-extensions", "sec-websocket-protocol",
        }
    ]
    try:
        async with websockets.connect(
            uri,
            origin=upstream_origin,
            subprotocols=scope.get("subprotocols", []),
            additional_headers=headers,
            proxy=None,
            max_size=8 * 1024 * 1024,
        ) as upstream:
            await send({"type": "websocket.accept", "subprotocol": upstream.subprotocol})

            async def browser_to_upstream():
                while True:
                    event = await receive()
                    if event["type"] == "websocket.disconnect":
                        return
                    if event["type"] == "websocket.receive":
                        payload = event.get("text") if event.get("text") is not None else event.get("bytes")
                        if payload is not None:
                            await upstream.send(payload)

            async def upstream_to_browser():
                async for payload in upstream:
                    if isinstance(payload, bytes):
                        await send({"type": "websocket.send", "bytes": payload})
                    else:
                        await send({"type": "websocket.send", "text": payload})

            tasks = {
                asyncio.create_task(browser_to_upstream()),
                asyncio.create_task(upstream_to_browser()),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exception = task.exception()
                if exception and not isinstance(exception, ConnectionClosed):
                    raise exception
    except (ConnectionClosed, OSError, websockets.WebSocketException):
        await send({"type": "websocket.close", "code": 1011})


def _origin_matches_hosts(origin: str, hosts: list[str]) -> bool:
    """Accept same-origin websocket handshakes, including default URL ports."""
    try:
        parsed_origin = urlsplit(origin)
        if parsed_origin.scheme not in {"http", "https"} or not parsed_origin.hostname:
            return False
        expected_port = parsed_origin.port or (443 if parsed_origin.scheme == "https" else 80)
        for candidate in hosts:
            parsed_host = urlsplit(f"//{candidate}")
            actual_port = parsed_host.port or expected_port
            if parsed_host.hostname and parsed_host.hostname.lower() == parsed_origin.hostname.lower() and actual_port == expected_port:
                return True
        return False
    except ValueError:
        return False
