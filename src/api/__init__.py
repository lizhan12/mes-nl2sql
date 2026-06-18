"""API 路由层。

按功能拆分为多个路由模块，由 main.py 统一注册：
- workflow: NL2SQL 工作流相关接口（nl2sql/chat/execute）
- harness: Harness 知识进化管理接口
- graph: 表关系图管理接口
- knowledge: 知识库管理接口（表/FewShot/RuntimeRule 等）
- trace: Trace 追踪查询接口
- auth: 认证接口
- users: 用户管理接口
"""
