import asyncio
import httpx
import json
from typing import Tuple


class SSEAdapter:
    def __init__(self, url: str, headers: dict | None = None):
        self.url = url
        self.headers = headers or {}
        self.client = httpx.AsyncClient(timeout=None)

        self.endpoint = None
        self.reader = asyncio.StreamReader()

    async def _start_sse_listener(self):
        print(f"[SSE] Opening SSE connection → {self.url}")

        try:
            async with self.client.stream("GET", self.url, headers=self.headers) as response:
                print(f"[SSE] Status: {response.status_code}")

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    print(f"[SSE RAW] {line}")

                    # -------------------------
                    # Handle SSE data
                    # -------------------------
                    if line.startswith("data:"):
                        data = line.replace("data:", "").strip()

                        print(f"[SSE DATA] {data}")

                        # First message = endpoint
                        if not self.endpoint:
                            self.endpoint = data
                            print(f"[SSE] ✅ Endpoint received: {self.endpoint}")
                            continue

                        # Subsequent messages = JSON-RPC
                        try:
                            parsed = json.loads(data)
                            print(f"[SSE JSON] {parsed}")

                            self.reader.feed_data((data + "\n").encode())

                        except Exception as e:
                            print(f"[SSE] Ignoring non-JSON message: {e}")

        except Exception as e:
            print(f"[SSE ERROR] Listener crashed: {e}")

        finally:
            print("[SSE] Listener ended")
            self.reader.feed_eof()

    async def connect(self) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        print("[SSE] Starting adapter connection...")

        asyncio.create_task(self._start_sse_listener())

        # Wait for endpoint
        for i in range(50):  # ~5 seconds
            if self.endpoint:
                break
            await asyncio.sleep(0.1)

        if not self.endpoint:
            raise RuntimeError("[SSE] ❌ Failed to receive endpoint")

        # Fix relative URL
        if self.endpoint.startswith("/"):
            base = self.url.split("/agentbuilder-api")[0]
            self.endpoint = base + self.endpoint

        print(f"[SSE] Final endpoint → {self.endpoint}")

        # -------------------------
        # Writer (POST channel)
        # -------------------------
        class Writer:
            async def write(inner_self, data):
                try:
                    print(f"[POST] Sending request → {data.decode()[:200]}")

                    response = await self.client.post(
                        self.endpoint,
                        content=data,
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        }
                    )

                    print(f"[POST] Response status: {response.status_code}")

                except Exception as e:
                    print(f"[POST ERROR] {e}")

            async def drain(inner_self):
                pass

            def close(inner_self):
                print("[POST] Writer closed")

        print("[SSE] ✅ Adapter ready")

        return self.reader, Writer()
