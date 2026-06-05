"""生成 LangGraph 工作流可视化图。"""

from src.graph.state import GraphState
from src.graph.workflow import build_workflow

# 传入 None 作为 stores，仅用于生成图结构
workflow = build_workflow(None, None)

# 获取图
graph = workflow.get_graph()

# 输出 Mermaid 格式（可在 GitHub、Notion 等渲染）
print("=== Mermaid ===")
print(graph.draw_mermaid())

# 保存 PNG 图片
png_path = "docs/graph_workflow.png"
import os

os.makedirs("docs", exist_ok=True)
with open(png_path, "wb") as f:
    f.write(graph.draw_mermaid_png())
print(f"\nPNG saved: {png_path}")
