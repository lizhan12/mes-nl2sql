/** 使用 fetch + ReadableStream 手动解析 SSE 流。 */
export async function fetchSSE(
  url: string,
  body: Record<string, unknown>,
  onEvent: (event: { node: string; status: string; thread_id: string; data: Record<string, unknown> }) => void,
  onError: (error: Error) => void,
  onComplete: () => void,
): Promise<AbortController> {
  const controller = new AbortController();

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("Response body is not readable");
    }

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      // 保留最后一个可能不完整的行
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;
          try {
            const event = JSON.parse(jsonStr);
            onEvent(event);
          } catch {
            // 跳过无法解析的行
          }
        }
      }
    }

    // 处理缓冲区剩余数据
    if (buffer.startsWith("data: ")) {
      const jsonStr = buffer.slice(6).trim();
      if (jsonStr) {
        try {
          const event = JSON.parse(jsonStr);
          onEvent(event);
        } catch {
          // ignore
        }
      }
    }
  } catch (error) {
    if ((error as DOMException).name !== "AbortError") {
      onError(error instanceof Error ? error : new Error(String(error)));
    }
  } finally {
    onComplete();
  }

  return controller;
}
