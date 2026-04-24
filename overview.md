# graphify 功能框架图

```mermaid
flowchart TD
    subgraph INPUT["📥 输入源"]
        SRC["源代码文件\n.py .js .ts .java\n.c .cpp .go .rs ..."]
        URL["外部 URL\narXiv / GitHub\nPDF / Web / YouTube"]
        CORPUS["本地语料\ncorpus/ 目录"]
    end

    subgraph CLI["🖥️ CLI 入口 (__main__.py)"]
        CMD_BUILD["graphify build\n构建知识图谱"]
        CMD_UPDATE["graphify update\n增量更新"]
        CMD_INGEST["graphify ingest\n摄取 URL"]
        CMD_QUERY["graphify query\n查询图谱"]
        CMD_PATH["graphify path\n最短路径"]
        CMD_WIKI["graphify wiki\n生成 Wiki"]
        CMD_SERVE["graphify serve\n启动 MCP 服务器"]
        CMD_INSTALL["graphify install\n安装 AI 技能"]
    end

    subgraph PIPELINE["⚙️ 核心处理流水线"]
        DETECT["detect.py\ncollect_files()\n过滤文件列表"]
        EXTRACT["extract.py\nextract()\ntree-sitter 多语言解析\n→ nodes + edges dict"]
        VALIDATE["validate.py\nvalidate_extraction()\nSchema 校验"]
        BUILD["build.py\nbuild_graph()\n构建 nx.Graph"]
        CLUSTER["cluster.py\ncluster()\nLouvain 社区检测\n标注 community 属性"]
        ANALYZE["analyze.py\nanalyze()\nGod节点 / 惊喜点 / 问题"]
        REPORT["report.py\nrender_report()\n生成 GRAPH_REPORT.md"]
    end

    subgraph CACHE["🗄️ 缓存层 (cache.py)"]
        CACHE_CHECK["check_semantic_cache()\n已缓存 vs 未缓存分拣"]
        CACHE_SAVE["save_semantic_cache()\n保存 API 提取结果"]
    end

    subgraph EXPORT["📤 导出层 (export.py)"]
        OUT_JSON["graph.json\nNetworkX JSON"]
        OUT_HTML["graph.html\n交互式可视化"]
        OUT_SVG["graph.svg\n静态矢量图"]
        OUT_OBS["obsidian/\nObsidian Vault 双链笔记"]
        OUT_RPT["GRAPH_REPORT.md\n图谱报告"]
    end

    subgraph WIKI["📚 Wiki 生成层 (wiki.py)"]
        WIKI_IDX["wiki/index.md\n导航索引"]
        WIKI_COM["wiki/community-N.md\n每个社区的文章"]
        WIKI_GOD["God节点详细文章\n跨社区链接关系"]
    end

    subgraph INGEST["🌐 内容摄取层 (ingest.py)"]
        ING_TYPE["URL 类型检测\ntweet / arxiv / github\nyoutube / pdf / webpage"]
        ING_FETCH["safe_fetch()\n内容抓取 + 大小限制"]
        ING_MD["输出 .md 文件\n→ corpus/ 目录"]
    end

    subgraph MCP["🔌 MCP 服务器层 (serve.py)"]
        MCP_QG["query_graph\nBFS / DFS 遍历查询"]
        MCP_GN["get_node\n节点详情"]
        MCP_NBR["get_neighbors\n邻居节点"]
        MCP_COM["get_community\n社区节点列表"]
        MCP_GOD["god_nodes\n最高连接度节点"]
        MCP_STAT["graph_stats\n图谱统计摘要"]
        MCP_PATH["shortest_path\n两节点最短路径"]
    end

    subgraph INSTALL["🔧 安装集成层"]
        SKILL["平台技能文件 SKILL.md\nclaude / codex / copilot\naider / opencode / kiro\ntrae / droid / gemini / claw"]
        HOOKS["hooks.py\nPostToolUse / PreToolUse\n代码变更自动重建钩子"]
        MANIFEST["manifest.py\nMCP 配置文件生成"]
    end

    subgraph SUPPORT["🛡️ 辅助支撑层"]
        SEC["security.py\nvalidate_url()\nsafe_fetch()\nvalidate_graph_path()\nsanitize_label()"]
        WATCH["watch.py\nwatch()\n文件系统监控\n变更触发重建"]
        TRANS["transcribe.py\nPDF / 视频文字转录"]
        BENCH["benchmark.py\n图谱 vs 语料 Token 对比"]
    end

    subgraph OUT_DIR["📁 graphify-out/"]
        OUT_JSON
        OUT_HTML
        OUT_SVG
        OUT_OBS
        OUT_RPT
        WIKI_IDX
        WIKI_COM
        WIKI_GOD
    end

    %% 输入流向
    SRC --> CMD_BUILD
    SRC --> CMD_UPDATE
    URL --> CMD_INGEST
    CORPUS --> CMD_BUILD

    %% CLI 触发流水线
    CMD_BUILD --> DETECT
    CMD_UPDATE --> DETECT

    %% 核心流水线
    DETECT --> EXTRACT
    EXTRACT --> CACHE_CHECK
    CACHE_CHECK -->|"未缓存"| VALIDATE
    CACHE_CHECK -->|"已缓存"| BUILD
    VALIDATE --> BUILD
    BUILD --> CLUSTER
    CLUSTER --> ANALYZE
    ANALYZE --> REPORT
    REPORT --> OUT_RPT

    %% 缓存写回
    VALIDATE --> CACHE_SAVE

    %% 导出
    CLUSTER --> EXPORT

    %% Wiki 生成
    CMD_WIKI --> WIKI_IDX
    ANALYZE --> WIKI_COM
    ANALYZE --> WIKI_GOD

    %% 摄取流程
    CMD_INGEST --> ING_TYPE
    ING_TYPE --> ING_FETCH
    ING_FETCH --> ING_MD
    ING_MD --> CORPUS
    SEC --> ING_FETCH

    %% MCP 服务器读取图谱
    CMD_SERVE --> MCP_QG
    OUT_JSON --> MCP_QG
    OUT_JSON --> MCP_GN
    OUT_JSON --> MCP_NBR
    OUT_JSON --> MCP_COM
    OUT_JSON --> MCP_GOD
    OUT_JSON --> MCP_STAT
    OUT_JSON --> MCP_PATH

    %% 查询命令
    CMD_QUERY --> MCP_QG
    CMD_PATH --> MCP_PATH

    %% 安装
    CMD_INSTALL --> SKILL
    CMD_INSTALL --> HOOKS
    CMD_INSTALL --> MANIFEST

    %% 监控触发
    WATCH --> CMD_UPDATE

    %% 安全校验覆盖输入
    SEC -.->|"校验所有外部输入"| EXTRACT
    SEC -.->|"校验图谱路径"| MCP_QG

    %% 样式
    classDef pipeline fill:#dbeafe,stroke:#3b82f6,color:#1e40af
    classDef io fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef mcp fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef support fill:#f3e8ff,stroke:#9333ea,color:#581c87
    classDef cli fill:#fff7ed,stroke:#ea580c,color:#7c2d12
    classDef cache fill:#fce7f3,stroke:#db2777,color:#831843

    class DETECT,EXTRACT,VALIDATE,BUILD,CLUSTER,ANALYZE,REPORT pipeline
    class SRC,URL,CORPUS,OUT_JSON,OUT_HTML,OUT_SVG,OUT_OBS,OUT_RPT,WIKI_IDX,WIKI_COM,WIKI_GOD,ING_MD io
    class MCP_QG,MCP_GN,MCP_NBR,MCP_COM,MCP_GOD,MCP_STAT,MCP_PATH mcp
    class SEC,WATCH,TRANS,BENCH,HOOKS,MANIFEST support
    class CMD_BUILD,CMD_UPDATE,CMD_INGEST,CMD_QUERY,CMD_PATH,CMD_WIKI,CMD_SERVE,CMD_INSTALL cli
    class CACHE_CHECK,CACHE_SAVE cache
```

## 核心概念说明

### 处理流水线

| 模块 | 函数 | 职责 |
|------|------|------|
| `detect.py` | `collect_files()` | 遍历目录，按扩展名过滤出可处理文件 |
| `extract.py` | `extract()` | 用 tree-sitter 解析源码，输出 `{nodes, edges}` dict |
| `validate.py` | `validate_extraction()` | 校验提取结果的 Schema 合规性 |
| `build.py` | `build_graph()` | 将提取结果列表合并为 NetworkX 图 |
| `cluster.py` | `cluster()` | Louvain 算法检测社区，为每个节点标注 `community` 属性 |
| `analyze.py` | `analyze()` | 识别 God 节点、惊喜连接、待审问题 |
| `report.py` | `render_report()` | 渲染 `GRAPH_REPORT.md` 供 AI Agent 快速定向 |

### 边的置信度标签

| 标签 | 含义 |
|------|------|
| `EXTRACTED` | 显式关系（import 语句、直接函数调用） |
| `INFERRED` | 推断关系（调用图二次分析、共现推导） |
| `AMBIGUOUS` | 不确定关系，标记供人工审核 |

### 支持的语言

Python · JavaScript · TypeScript · Java · C# · C · C++ · Go · Ruby · Rust · Swift · Lua · Markdown · PDF · 网页
