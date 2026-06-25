import { BookOpen, Brain, Database, FileText, GitBranch, Network, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

import { Panel } from "@/components/Panel";

const sections = [
  {
    to: "/knowledge",
    icon: <Database className="h-5 w-5" />,
    title: "表知识库",
    desc: "管理 MES 表结构、字段和场景描述",
  },
  {
    to: "/graph",
    icon: <Network className="h-5 w-5" />,
    title: "表关系图",
    desc: "可视化和管理表之间的 JOIN 关系",
  },
  {
    to: "/few-shot",
    icon: <Sparkles className="h-5 w-5" />,
    title: "FewShot 示例",
    desc: "管理 NL2SQL 的少样本示例，支持结构化匹配",
  },
  {
    to: "/rule",
    icon: <FileText className="h-5 w-5" />,
    title: "运行时规则",
    desc: "管理查询时强制应用的硬约束规则",
  },
  {
    to: "/entity-lexicon",
    icon: <BookOpen className="h-5 w-5" />,
    title: "实体词典",
    desc: "管理业务实体词→域的映射和动作类型规则",
  },
  {
    to: "/harness",
    icon: <Brain className="h-5 w-5" />,
    title: "数据飞轮",
    desc: "失败案例分析、候选规则审核与发布",
  },
  {
    to: "/knowledge-search",
    icon: <GitBranch className="h-5 w-5" />,
    title: "知识检索",
    desc: "语义搜索知识库中的表结构和 FewShot 示例",
  },
];

export default function Home() {
  return (
    <div className="flex flex-col gap-6">
      <Panel title="MES 知识库管理">
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
          统一管理 MES 系统的结构化知识：表结构定义、表关系图、FewShot 示例、运行时规则、实体词典、
          通用知识库和数据飞轮。所有知识数据存储在 Neo4j
          图数据库中，支持语义检索和结构化精确匹配。
        </p>
      </Panel>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {sections.map((section) => (
          <Link
            key={section.to}
            to={section.to}
            className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-overlay)] p-5 transition-colors hover:border-[var(--accent)] hover:bg-[var(--bg-subtle)]"
          >
            <div className="mb-3 flex items-center gap-2.5 text-[var(--accent)]">
              {section.icon}
              <span className="font-medium text-[var(--text-primary)]">{section.title}</span>
            </div>
            <p className="text-sm leading-relaxed text-[var(--text-tertiary)]">{section.desc}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
