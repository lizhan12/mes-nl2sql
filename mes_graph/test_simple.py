"""简单测试脚本：验证项目基本结构和核心组件"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_imports():
    """测试所有模块导入是否正常"""
    print("=== 测试模块导入 ===")
    
    try:
        from src.core.config import settings
        print("✓ src.core.config")
    except Exception as e:
        print(f"✗ src.core.config: {e}")
        
    try:
        from src.graph.state import GraphState
        print("✓ src.graph.state")
    except Exception as e:
        print(f"✗ src.graph.state: {e}")
        
    try:
        from src.graph.nodes import (
            node_1_intent_understanding,
            node_2_parallel_retrieval,
            node_3_bfs_expand,
            node_4_schema_assembly,
            node_5_sql_generation,
            node_6_safety_check,
            node_7_execute_and_repair,
        )
        print("✓ src.graph.nodes")
    except Exception as e:
        print(f"✗ src.graph.nodes: {e}")
        
    try:
        from src.graph.workflow import build_workflow
        print("✓ src.graph.workflow")
    except Exception as e:
        print(f"✗ src.graph.workflow: {e}")
        
    try:
        from src.services.bfs import bfs_expand, find_path_between
        print("✓ src.services.bfs")
    except Exception as e:
        print(f"✗ src.services.bfs: {e}")
        
    try:
        from src.services.llm import get_llm, get_intent_llm
        print("✓ src.services.llm")
    except Exception as e:
        print(f"✗ src.services.llm: {e}")
        
    try:
        from src.utils.sql_validator import validate_sql
        print("✓ src.utils.sql_validator")
    except Exception as e:
        print(f"✗ src.utils.sql_validator: {e}")
        
    try:
        from src.harness.knowledge import load_cases, load_runtime_rules
        print("✓ src.harness.knowledge")
    except Exception as e:
        print(f"✗ src.harness.knowledge: {e}")

def test_bfs_expand():
    """测试 BFS 图扩展功能"""
    print("\n=== 测试 BFS 图扩展 ===")
    from src.services.bfs import bfs_expand, _GRAPH
    
    print(f"图中表数量: {len(_GRAPH)}")
    
    seed_tables = ["t_pd_wo"]
    result = bfs_expand(seed_tables, max_hops=2, max_tables=5)
    print(f"从 {seed_tables} 扩展出 {len(result['tables'])} 个表:")
    for table in result['tables'][:5]:
        print(f"  - {table}")
    
    if result['join_paths']:
        print(f"找到 {len(result['join_paths'])} 条 JOIN 路径")

def test_sql_validator():
    """测试 SQL 安全校验"""
    print("\n=== 测试 SQL 安全校验 ===")
    from src.utils.sql_validator import validate_sql
    
    test_cases = [
        ("SELECT * FROM t_pd_wo LIMIT 10", True),
        ("DELETE FROM t_pd_wo", False),
        ("DROP TABLE t_pd_wo", False),
        ("INSERT INTO t_pd_wo VALUES (1, 'test')", False),
    ]
    
    for sql, expected_safe in test_cases:
        result = validate_sql(sql)
        status = "✓" if result['safe'] == expected_safe else "✗"
        print(f"{status} {'安全' if result['safe'] else '危险'}: {sql[:50]}...")
        if not result['safe']:
            print(f"   原因: {result['error']}")

def test_knowledge_base():
    """测试知识库加载"""
    print("\n=== 测试知识库加载 ===")
    from src.harness.knowledge import load_cases, load_runtime_rules
    
    cases = load_cases()
    print(f"测试用例数量: {len(cases)}")
    
    rules = load_runtime_rules()
    print(f"运行时规则数量: {len(rules)}")
    
    # 检查数据文件是否存在
    import os
    data_files = [
        "data/mes_knowledge_base.txt",
        "data/mes_relation_graph.json",
        "data/dify_few_shot.txt",
        "data/dify_sql_prompt.txt",
    ]
    
    for f in data_files:
        exists = os.path.exists(f)
        status = "✓" if exists else "✗"
        print(f"{status} {f}")

def test_api_schema():
    """测试 API 模型定义"""
    print("\n=== 测试 API 模型 ===")
    from src.models.schemas import NL2SQLRequest, NL2SQLResponse, HealthResponse
    
    # 测试请求模型
    req = NL2SQLRequest(query="测试问题")
    print(f"✓ NL2SQLRequest: {req}")
    
    # 测试响应模型
    resp = NL2SQLResponse(
        query="测试问题",
        sql="SELECT * FROM test",
        safe=True,
        error="",
        tables_used=["test"],
        join_hints="",
        execution_result={"success": True, "rows": 0},
        retry_count=0,
        request_id="test-id",
        knowledge_version="v1",
    )
    print(f"✓ NL2SQLResponse: {resp.query}")
    
    # 测试健康检查响应
    health = HealthResponse(status="ok")
    print(f"✓ HealthResponse: {health}")

def test_config():
    """测试配置加载"""
    print("\n=== 测试配置加载 ===")
    from src.core.config import settings
    
    print(f"LLM 模型: {settings.llm_model}")
    print(f"意图模型: {settings.intent_model}")
    print(f"数据库: {settings.database_url}")
    print(f"BFS 最大跳数: {settings.bfs_max_hops}")
    print(f"默认 LIMIT: {settings.default_limit}")

if __name__ == "__main__":
    print("="*60)
    print("MES NL2SQL 项目端到端测试")
    print("="*60)
    
    test_imports()
    test_config()
    test_bfs_expand()
    test_sql_validator()
    test_knowledge_base()
    test_api_schema()
    
    print("\n" + "="*60)
    print("测试完成！")
    print("="*60)