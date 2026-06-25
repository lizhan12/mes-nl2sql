"""用 /v1/completions + Qwen3-Reranker 官方 prompt 跑 10 条候选。"""

import asyncio
import math

import httpx


QUERY = "查询包装规则为69b254c9a059eeeb74c433aa明细"

SCHEMA = [
    ("t_packing_rule", "包装规则配置表，用于定义产品或订单的包装规范，关联包装层级和容器信息"),
    ("t_packing_rule_detail", "包装规则明细表，定义各包装层级的容器、容量、检查类型（不管控/同料号/同工单/同批次等）、是否称重等详细规范"),
    ("t_wms_doc_upn", "UPN单据关联表，记录仓库单据与物料唯一编号(UPN)的关联关系，实现物料精确追溯"),
    ("t_wms_wo_material_bill_detail", "生产领料单明细表，记录领料单中具体物料的领用数量、已出数量、交接数量等行项目"),
    ("t_packing_container", "包装容器定义表，记录容器的名称、容量、类型、标签来源（自产/外部）等属性，是包装规则的基础数据"),
    ("t_bc_encode_rule", "编码规则定义，配置条码/序列号的生成规则，包括前缀、流水号、日期格式等编码模板"),
    ("t_lb_label_parse_rule_group", "标签解析规则组，定义从产线设备获取的标签数据的解析规则"),
    ("t_bc_encode_rule_group", "编码规则组，将多个编码规则组合为规则组，供物料料号引用以确定其条码编码方式"),
    ("t_pd_sn_defect_detail", "SN缺陷明细"),
    ("t_tool_maintenance_info", "工装治具维保记录表，记录治具的报修、维修等维保事件"),
]

QWEN3_RERANKER_INSTRUCT = (
    "Given a web search query, retrieve relevant passages that answer the query"
)
QWEN3_PROMPT_TEMPLATE = (
    "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n"
    "<|im_start|>user\n"
    "<Instruct>: {instruct}\n"
    "<Query>: {query}\n"
    "<Document>: {doc}<|im_end|>\n"
    "<|im_start|>assistant\n<think>\n\n</think>\n\n"
)


async def score_one(client, query, doc):
    prompt = QWEN3_PROMPT_TEMPLATE.format(
        instruct=QWEN3_RERANKER_INSTRUCT, query=query, doc=doc,
    )
    r = await client.post(
        "http://192.168.0.76:8001/v1/completions",
        headers={"Authorization": "Bearer sk-wlmdnlcicswgoealbouetyyuedswzyousvwfqgazncwqkxgo",
                 "Content-Type": "application/json"},
        json={
            "model": "qwen3-reranker-8b",
            "prompt": prompt,
            "max_tokens": 1,
            "temperature": 0.0,
            "logprobs": 20,
        },
    )
    data = r.json()
    if "choices" not in data:
        return None, f"no choices: {data}"
    choice = data["choices"][0]
    top = choice.get("logprobs", {}).get("top_logprobs", [{}])[0]
    if not top:
        return None, f"no top_logprobs: {choice}"
    # vLLM 输出的 yes/no 不一定严格带空格，包含中英文多种形式
    yes_keys = ("是", " yes", "Yes", "yes", "YES", " correct", "Correct", "True", " true")
    no_keys = ("没有", " no", "No", "no", "NO", " none", "None", "无关", " 未", " 不", "无", "0")
    # 找 yes/no 中 logprob 最大（即最 confident）的 token
    yes_lp = max((top[k] for k in yes_keys if k in top), default=None)
    no_lp = max((top[k] for k in no_keys if k in top), default=None)
    # 如果一边没出现在 top tokens 里，用一个非常小的 logprob 兜底
    # （vLLM top_logprobs 默认只返 20 个 token，可能全是 yes 类，此时 no 概率 ≈ 0）
    FALLBACK = -20.0
    if yes_lp is None:
        yes_lp = FALLBACK
    if no_lp is None:
        no_lp = FALLBACK
    # softmax
    p_yes = math.exp(yes_lp)
    p_no = math.exp(no_lp)
    score = p_yes / (p_yes + p_no)
    return score, None


async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        scored = []
        for name, doc in SCHEMA:
            score, err = await score_one(client, QUERY, doc)
            if err:
                print(f"  {name}: ERROR {err}")
            else:
                scored.append((name, doc, score))
        print()
        print("=== 官方 prompt + /v1/completions 评分 ===")
        for name, doc, score in sorted(scored, key=lambda x: -x[2]):
            print(f"  score={score:.4f}  {name:35s}  {doc[:30]}")


if __name__ == "__main__":
    asyncio.run(main())
