import asyncio
import httpx
from typing import Tuple
from urllib.parse import urljoin


class SSEAdapter:
    def __init__(self, url: str, headers: dict | None = None):
        self.url = url
        self.headers = headers or {}

    async def _get_endpoint(self) -> str:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", self.url, headers=self.headers) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        endpoint = line.replace("data:", "").strip()

                        if endpoint.startswith("/"):
                            base = self.url.split("/agentbuilder-api")[0]
                            endpoint = urljoin(base, endpoint)

                        print(f"[SSE] endpoint received: {endpoint}")
                        return endpoint

        raise RuntimeError("Failed to get endpoint")

    async def connect(self) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        endpoint = await self._get_endpoint()

        client = httpx.AsyncClient(timeout=None)

        reader = asyncio.StreamReader()

        async def pump():
            try:
                # 🔥 IMPORTANT: Use POST for MCP requests
                async with client.stream(
                    "GET", endpoint, headers=self.headers
                ) as response:
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data = line.replace("data:", "").strip()
                            reader.feed_data((data + "\n").encode())

            except Exception as e:
                print("[SSE ERROR]", e)
            finally:
                reader.feed_eof()

        asyncio.create_task(pump())

        class Writer:
            async def write(self, data):
                try:
                    # 🔥 Send MCP requests via POST
                    await client.post(
                        endpoint,
                        content=data,
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        }
                    )
                except Exception as e:
                    print("[POST ERROR]", e)

            async def drain(self):
                pass

            def close(self):
                pass

        return reader, Writer()
