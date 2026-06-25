"""打印 generative_scoring 端点的详细 schema。"""

import asyncio
import json

import httpx


async def main():
    url = "http://192.168.0.76:8001/openapi.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url)
        data = r.json()

    path = data["paths"].get("/generative_scoring", {})
    print(json.dumps(path, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
