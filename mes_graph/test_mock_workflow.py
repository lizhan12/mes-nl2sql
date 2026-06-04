"""模拟工作流测试：验证 NL2SQL 核心流程逻辑（跳过 LLM 和向量检索）"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from unittest.mock import Mock, patch
import json

def test_workflow_with_mocks():
    """测试完整工作流（使用模拟数据）"""
    print("=== 测试完整工作流（模拟模式）===")
    
    # Mock LLM 调用
    mock_intent_response = json.dumps({
        "anchor_tables": ["t_pd_wo"],
        "search_queries": ["工单", "工单查询"],
        "time_range": "",
        "filters": [],
        "ambiguity": ""
    })
    
    mock_sql_response = """SELECT wo.work_order_no, wo.product_code, wo.qty, wo.status
FROM t_pd_wo wo
WHERE wo.status = 'COMPLETED'
ORDER BY wo.create_time DESC
LIMIT 500;"""
    
    with patch('src.services.llm.get_intent_llm') as mock_intent_llm, \
         patch('src.services.llm.get_llm') as mock_llm, \
         patch('src.services.vector_store.search_schema') as mock_search_schema, \
         patch('src.services.vector_store.search_few_shot') as mock_search_few_shot:
        
        # 设置 mock 返回值
        mock_intent_llm.return_value.invoke.return_value.content = mock_intent_response
        mock_llm.return_value.invoke.return_value.content = mock_sql_response
        
        # 设置向量检索返回空（模拟无向量库）
        mock_search_schema.return_value = []
        mock_search_few_shot.return_value = []
        
        # 导入工作流组件
        from src.graph.workflow import build_workflow
        from src.graph.state import GraphState
        
        # 创建模拟的向量存储
        mock_schema_store = Mock()
        mock_few_shot_store = Mock()
        
        # 构建工作流
        try:
            app = build_workflow(mock_schema_store, mock_few_shot_store)
            print("✓ 工作流构建成功")
        except Exception as e:
            print(f"✗ 工作流构建失败: {e}")
            return
        
        # 测试执行工作流
        test_query = "查询最近完成的工单"
        print(f"\n测试查询: {test_query}")
        
        try:
            result = app.invoke({"query": test_query})
            print("✓ 工作流执行成功")
            
            # 检查结果
            print(f"\n执行结果:")
            print(f"  generated_sql: {result.get('generated_sql', '')[:100]}...")
            print(f"  final_sql: {result.get('final_sql', '')[:100]}...")
            print(f"  safe: {result.get('safe')}")
            print(f"  expanded_tables: {result.get('expanded_tables')}")
            print(f"  retry_count: {result.get('retry_count', 0)}")
            
            # 验证 SQL 安全校验
            if result.get('safe'):
                print("✓ SQL 通过安全校验")
            else:
                print(f"✗ SQL 未通过安全校验: {result.get('error')}")
                
        except Exception as e:
            print(f"✗ 工作流执行失败: {e}")
            import traceback
            traceback.print_exc()

def test_bfs_path_finding():
    """测试 BFS 路径查找功能"""
    print("\n=== 测试 BFS 路径查找 ===")
    
    from src.services.bfs import bfs_expand, find_path_between, build_join_hints
    
    # 测试从工单表扩展
    seed_tables = ["t_pd_wo"]
    result = bfs_expand(seed_tables, max_hops=2, max_tables=10)
    
    print(f"从 {seed_tables} 扩展出 {len(result['tables'])} 个表")
    print(f"表列表: {sorted(result['tables'])}")
    
    if result['join_paths']:
        print(f"\nJOIN 路径 ({len(result['join_paths'])} 条):")
        join_hints = build_join_hints(result['join_paths'])
        for line in join_hints.split('\n')[:5]:
            print(f"  {line}")
    
    # 测试跨表路径查找
    path = find_path_between("t_pd_wo", "t_ems_equipment", max_depth=4)
    if path:
        print(f"\n工单到设备的路径: {' → '.join(path)}")
    else:
        print("\n未找到工单到设备的路径")

def test_sql_validation():
    """测试 SQL 安全校验"""
    print("\n=== 测试 SQL 安全校验 ===")
    
    from src.utils.sql_validator import validate_sql
    
    test_cases = [
        ("SELECT * FROM t_pd_wo WHERE status = 'COMPLETED'", True),
        ("SELECT * FROM t_pd_wo", True),
        ("DELETE FROM t_pd_wo", False),
        ("DROP TABLE t_pd_wo", False),
        ("INSERT INTO t_pd_wo (id) VALUES (1)", False),
        ("UPDATE t_pd_wo SET status = 'TEST'", False),
    ]
    
    all_passed = True
    for sql, expected_safe in test_cases:
        result = validate_sql(sql)
        passed = result['safe'] == expected_safe
        status = "✓" if passed else "✗"
        all_passed &= passed
        print(f"{status} {'安全' if result['safe'] else '危险'}: {sql[:60]}")
        if not passed:
            print(f"   预期: {'安全' if expected_safe else '危险'}, 实际: {'安全' if result['safe'] else '危险'}")
    
    if all_passed:
        print("✓ 所有安全校验测试通过")
    else:
        print("✗ 部分安全校验测试失败")

def test_intent_parsing():
    """测试意图解析逻辑"""
    print("\n=== 测试意图解析 ===")
    
    from src.graph.nodes import _parse_intent_json, _build_query_constraints
    
    # 测试解析意图 JSON
    raw_intent = '{"anchor_tables": ["t_pd_wo"], "search_queries": ["工单", "完成"], "time_range": "", "filters": [], "ambiguity": ""}'
    intent = _parse_intent_json(raw_intent)
    
    print(f"解析意图: {intent}")
    print(f"锚点表: {intent.get('anchor_tables')}")
    print(f"搜索词: {intent.get('search_queries')}")
    
    # 测试构建查询约束
    query = "查询最近一周完成的工单"
    enriched_intent, guidance = _build_query_constraints(query, intent)
    
    print(f"\n增强后的意图:")
    print(f"  锚点表: {enriched_intent.get('anchor_tables')}")
    print(f"  搜索词: {enriched_intent.get('search_queries')}")
    print(f"  查询指导: {guidance}")

def test_knowledge_files():
    """测试知识库文件加载"""
    print("\n=== 测试知识库文件 ===")
    
    from pathlib import Path
    
    data_dir = Path("data")
    
    files_to_check = [
        ("mes_knowledge_base.txt", "表结构知识库"),
        ("mes_relation_graph.json", "表关系图"),
        ("dify_few_shot.txt", "SQL 示例库"),
        ("dify_sql_prompt.txt", "SQL 生成模板"),
    ]
    
    for filename, description in files_to_check:
        filepath = data_dir / filename
        if filepath.exists():
            size = filepath.stat().st_size
            print(f"✓ {description} ({filename}): {size} 字节")
            
            # 读取前几行查看内容
            if size < 10000:
                content = filepath.read_text(encoding="utf-8")
                lines = content.split('\n')
                print(f"  行数: {len(lines)}")
        else:
            print(f"✗ {description} ({filename}): 不存在")

if __name__ == "__main__":
    print("="*60)
    print("MES NL2SQL 端到端测试（模拟模式）")
    print("说明：由于当前环境没有 PostgreSQL + pgvector，")
    print("此测试使用模拟数据验证核心流程逻辑")
    print("="*60)
    
    test_knowledge_files()
    test_bfs_path_finding()
    test_sql_validation()
    test_intent_parsing()
    test_workflow_with_mocks()
    
    print("\n" + "="*60)
    print("测试完成！")
    print("="*60)