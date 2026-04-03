# server/sse_bridge.py
import asyncio
import sys
import json
import httpx
from urllib.parse import urlparse


async def main_bridge(sse_url, api_key, base_prefix=""):
    sse_headers = {
        "x-api-key": api_key,
        "Accept": "text/event-stream",
        "Cache-Control": "no-store",
    }
    post_headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }

    # Shared state
    post_url_ready = asyncio.Event()
    post_url = None

    # Queue to buffer stdin messages before the SSE endpoint is ready
    msg_queue: asyncio.Queue = asyncio.Queue()

    async with httpx.AsyncClient(timeout=None, verify=False) as client:

        async def sse_reader():
            """
            Keep ONE SSE connection open forever.
            """
            nonlocal post_url
            endpoint_received = False

            async with client.stream("GET", sse_url, headers=sse_headers) as sse:
                sse.raise_for_status()
                sys.stderr.write("[bridge] SSE connected\n")

                async for line in sse.aiter_lines():

                    if not line or line.startswith(":"):
                        continue

                    if line.startswith("event:"):
                        continue

                    if line.startswith("data:"):
                        payload = line[len("data:"):].strip()

                        if not endpoint_received:
                            if base_prefix and not payload.startswith(base_prefix):
                                fixed_path = base_prefix + payload
                            else:
                                fixed_path = payload

                            parsed = urlparse(sse_url)
                            post_url = f"{parsed.scheme}://{parsed.netloc}{fixed_path}"
                            sys.stderr.write(f"[bridge] Endpoint → {post_url}\n")
                            endpoint_received = True
                            post_url_ready.set()

                        else:
                            if payload:
                                try:
                                    json.loads(payload)
                                    # Use binary buffer for reliable stdout on Windows
                                    sys.stdout.buffer.write((payload + "\n").encode('utf-8'))
                                    sys.stdout.buffer.flush()
                                    sys.stderr.write(f"[bridge] → stdout: {payload[:80]}...\n")
                                except json.JSONDecodeError:
                                    sys.stderr.write(f"[bridge] Non-JSON data skipped: {payload[:60]}\n")

        async def stdin_reader():
            """
            Read stdin immediately into a queue — does NOT wait for the SSE endpoint.
            This prevents the race condition where the MCP parent sends 'initialize'
            before the SSE endpoint is discovered.
            """
            loop = asyncio.get_event_loop()
            sys.stderr.write("[bridge] stdin_reader started, buffering input...\n")

            while True:
                # Portable binary stdin read (works on Windows & Unix)
                line = await loop.run_in_executor(None, sys.stdin.buffer.readline)

                if not line:
                    sys.stderr.write("[bridge] stdin closed\n")
                    await msg_queue.put(None)  # Signal sender to stop
                    break

                cleaned = line.strip().decode('utf-8')
                if cleaned:
                    await msg_queue.put(cleaned)

        async def message_sender():
            """
            Wait for SSE endpoint to be ready, then drain the queue and forward
            all buffered + future JSON-RPC messages to the SSE POST endpoint.
            """
            await post_url_ready.wait()
            sys.stderr.write("[bridge] message_sender ready, forwarding queued messages...\n")

            while True:
                msg = await msg_queue.get()
                if msg is None:
                    break  # stdin closed
                try:
                    payload = json.loads(msg)
                    method = payload.get("method", "?")
                    resp = await client.post(post_url, json=payload, headers=post_headers)
                    sys.stderr.write(f"[bridge] POST {method} → {resp.status_code}\n")
                except json.JSONDecodeError as e:
                    sys.stderr.write(f"[bridge] Bad JSON from stdin: {e}\n")
                except Exception as e:
                    sys.stderr.write(f"[bridge] POST error: {e}\n")

        await asyncio.gather(sse_reader(), stdin_reader(), message_sender())


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.stderr.write("Usage: sse_bridge.py <sse_url> <api_key> [base_prefix]\n")
        sys.exit(1)

    u = sys.argv[1]
    k = sys.argv[2]
    p = sys.argv[3] if len(sys.argv) > 3 else ""
    
    asyncio.run(main_bridge(u, k, p))
