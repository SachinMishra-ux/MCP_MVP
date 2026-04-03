import asyncio
import httpx
import json
from typing import Tuple


class SSEAdapter:
    def __init__(self, url: str, headers: dict | None = None):
        self.url = url
        self.headers = headers or {}
        self.client = httpx.AsyncClient(timeout=None)

    async def _extract_endpoint(self) -> str:
        """
        Step 1:
        Connect to initial SSE endpoint and extract actual MCP endpoint
        """
        async with self.client.stream("GET", self.url, headers=self.headers) as response:
            async for line in response.aiter_lines():
                if not line:
                    continue

                # DEBUG (you can comment later)
                # print("[SSE INIT RAW]", line)

                if line.startswith("data:"):
                    endpoint = line.replace("data:", "").strip()

                    if not endpoint:
                        continue

                    # Convert relative → absolute URL
                    if endpoint.startswith("/"):
                        base = self.url.split("/sse")[0]
                        endpoint = base + endpoint

                    print(f"[SSE] Received endpoint: {endpoint}")
                    return endpoint

        raise RuntimeError("Failed to get MCP endpoint from SSE")

    async def connect(self) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """
        Step 2:
        Connect to actual MCP SSE stream and convert → stdio-like stream
        """
        endpoint = await self._extract_endpoint()

        response = await self.client.stream("GET", endpoint, headers=self.headers)

        reader = asyncio.StreamReader()

        async def pump():
            try:
                async for line in response.aiter_lines():
                    if not line:
                        continue

                    # DEBUG
                    # print("[SSE STREAM RAW]", line)

                    if line.startswith("data:"):
                        data = line.replace("data:", "").strip()

                        if not data:
                            continue

                        try:
                            # Ensure it's valid JSON (important!)
                            json.loads(data)

                            # Feed into MCP stream
                            reader.feed_data((data + "\n").encode())

                        except Exception:
                            # Ignore non-JSON (ping, comments, etc.)
                            continue

            except Exception as e:
                print(f"[SSE ERROR] {e}")
            finally:
                reader.feed_eof()

        asyncio.create_task(pump())

        class DummyWriter:
            def write(self, data):
                # MCP client may send requests → ignore or extend later
                pass

            async def drain(self):
                pass

            def close(self):
                pass

        return reader, DummyWriter()