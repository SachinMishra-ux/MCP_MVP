import asyncio
import json
import httpx
from urllib.parse import urlparse, urljoin


class SSEBridgeTransport:
    def __init__(self, sse_url: str, api_key: str):
        self.sse_url = sse_url
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=None)

        self.post_url = None
        self.post_url_ready = asyncio.Event()

        self.read_queue = asyncio.Queue()

    async def start(self):
        asyncio.create_task(self._sse_reader())

    async def _sse_reader(self):
        headers = {
            "x-api-key": self.api_key,
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        }

        current_event = None

        async with self.client.stream("GET", self.sse_url, headers=headers) as sse:
            sse.raise_for_status()
            print("[SSEBridge] Connected to SSE")

            async for line in sse.aiter_lines():
                if not line or line.startswith(":"):
                    continue

                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                    continue

                if line.startswith("data:"):
                    payload = line[len("data:"):].strip()

                    # 🔥 Endpoint handling
                    if current_event == "endpoint":
                        parsed = urlparse(self.sse_url)
                        base = f"{parsed.scheme}://{parsed.netloc}"
                        self.post_url = urljoin(base, payload)

                        print(f"[SSEBridge] POST URL → {self.post_url}")
                        self.post_url_ready.set()
                        continue

                    # 🔥 JSON-RPC messages
                    if current_event == "message":
                        try:
                            json.loads(payload)
                            await self.read_queue.put(payload)
                        except:
                            print("[SSEBridge] Invalid JSON skipped")

    async def read(self):
        return await self.read_queue.get()

    async def write(self, data: str):
        await asyncio.wait_for(self.post_url_ready.wait(), timeout=15)

        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = json.loads(data)

        resp = await self.client.post(self.post_url, json=payload, headers=headers)
        print(f"[SSEBridge] POST {payload.get('method')} → {resp.status_code}")