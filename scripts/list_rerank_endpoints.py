"""打印 vLLM Rerank 服务的完整 OpenAPI 路径清单。"""

import asyncio
import json

import httpx


async def main():
    url = "http://192.168.0.76:8001/openapi.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url)
        data = r.json()

    paths = data.get("paths", {})
    print(f"Total paths: {len(paths)}")
    print()
    for path, methods in sorted(paths.items()):
        for method, info in methods.items():
            summary = info.get("summary", "")
            op_id = info.get("operationId", "")
            print(f"  {method.upper():6s} {path:40s}  {summary}  [{op_id}]")


if __name__ == "__main__":
    asyncio.run(main())
