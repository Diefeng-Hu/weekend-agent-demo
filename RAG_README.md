# 北京周末游 RAG 模块

本目录包含一个轻量 RAG 推荐模块，用于在当前“周末规划助手”中提供“北京常见周末游路线”的静态知识库参考。它适合补充攻略型路线建议，不替代 `demo.html` 中的实时 POI、天气、营业状态和路线判断。

## 文件说明

- `rag_module.py`：RAG 模块代码，包含数据加载、增量写入、检索、推荐理由生成和 CLI 演示。
- `beijing_routes.json`：示例北京周末游路线数据集。
- `chroma_beijing_routes/`：可选 Chroma 向量库目录，启用 LangChain 模式后自动生成。

## 快速运行

无需额外依赖即可运行本地 TF-IDF 检索：

```bash
python3 rag_module.py "适合家庭的周末游" --top-k 3
```

输出 JSON：

```bash
python3 rag_module.py "雨天室内约会" --top-k 3 --json
```

## Python 调用示例

```python
from rag_module import BeijingRouteRAG

rag = BeijingRouteRAG(data_path="beijing_routes.json")
result = rag.recommend("适合家庭的周末游", top_k=3)
print(result["recommendations"])
```

## 对话系统集成示例

在当前 Demo 架构中，RAG 更适合作为“路线灵感/攻略补充”工具：当用户的问题包含“北京、周末、路线、亲子、情侣、朋友、攻略”等意图时调用；最终方案仍应经过实时 POI 搜索、天气日期对齐、距离过滤、营业时间过滤和预算估算。

```python
rag = BeijingRouteRAG()

async def handle_chat(user_text: str):
    if "北京" in user_text or "周末" in user_text:
        rag_result = rag.recommend(user_text, top_k=3)
        return rag_result
    return await original_chat_handler(user_text)
```

## 可选 LangChain + Chroma 模式

如果需要向量数据库语义检索，可安装依赖并配置 OpenAI Key：

```bash
pip install langchain langchain-openai langchain-chroma chromadb
export OPENAI_API_KEY=你的Key
python3 rag_module.py "适合家庭的周末游" --top-k 3 --langchain
```

未安装依赖或未配置 `OPENAI_API_KEY` 时，模块会自动回退到本地 TF-IDF 检索，保证 demo 可复现。

## 增量添加新路线

```python
from rag_module import add_route

add_route({
    "id": "bj_new_route",
    "title": "新路线标题",
    "suitable_for": ["亲子", "半日游"],
    "duration": "4小时",
    "estimated_cost_per_person": 120,
    "spots": ["地点A", "地点B"],
    "route": "上午去地点A，中午在地点B用餐。",
    "highlights": ["距离近", "适合孩子"],
    "tips": "建议提前预约。"
})
```

再次初始化 `BeijingRouteRAG` 即可检索新增路线。

## 与当前 Demo 的关系

- `demo.html`：负责实时规划，包含 POI 搜索、天气、营业时间、局部重绘和计划卡。
- `rag_module.py`：负责静态路线知识检索，适合回答“北京有什么周末路线/亲子路线/雨天路线”。
- 推荐使用方式：先用 RAG 找路线灵感，再用实时 POI 和天气工具校验是否可执行。
- 不建议：只用 RAG 结果直接生成最终计划，因为路线数据可能不包含实时营业、预约、天气和距离信息。

## 验收点

- 默认查询返回 Top-3 路线。
- 每条路线包含标题、景点、时长、路线、人均预估和推荐理由。
- 本地 TF-IDF 检索无需网络，数据量较小时响应通常低于 2 秒。
- 通过 `add_route()` 支持增量添加新路线，并按 `id` 去重替换。
- 输出路线用于规划前参考，最终方案仍需经过实时工具校验。
