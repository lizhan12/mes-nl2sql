# Debug Session: enable-thinking-error

## Session ID
`enable-thinking-error`

## Status: [FIXED]

## Error Description
- **Error**: `Completions.create() got an unexpected keyword argument 'enable_thinking'`
- **Symptom**: 调用 LLM API 时传递了不支持的参数 `enable_thinking`
- **Context**: 用户询问工单合格率时触发此错误

## Root Cause
`src/services/llm.py` 第 17-18 行试图通过 `extra_body` 和 `model_kwargs` 传递 `enable_thinking: False` 参数，但 API 服务器（`http://192.168.0.209:8001/v1`）不支持此参数。

## Fix Applied
注释掉 `src/services/llm.py` 中的 `enable_thinking` 相关代码：
```python
# "extra_body": {"enable_thinking": False},
# "model_kwargs": {"enable_thinking": False},
```

## Verification
请重新请求"工单有多少是合格的"，验证错误是否消失

## Cleanup
- [x] 已修复代码
- [ ] 待用户验证
