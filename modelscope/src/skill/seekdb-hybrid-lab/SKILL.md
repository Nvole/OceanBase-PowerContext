---
name: seekdb-hybrid-lab
version: 0.1.0
description: "指导使用 OceanBase seekdb 完成一次最小混合检索实验：用 upsert 写入三条文档、显式向量和元数据，调用 refresh_index 刷新索引，再调用 hybrid_search。全文条件使用 query.where_document.$contains，向量条件使用 knn.query_embeddings，融合排序使用 rank.rrf。适用于核对混合检索参数和复现三条样例；不要用于读取密钥、改写示例以外的数据，也不要在没有查询返回时编造命中文档。"
---

# seekdb 混合检索实验

## 1. 这个 Skill 做什么

名称是 `seekdb-hybrid-lab`。它只覆盖一次最小混合检索实验，用来核对 pyseekdb Collection 的调用顺序和参数位置。

按顺序做三件事：

1. `upsert`：写入下面的三条示例数据。
2. `refresh_index`：刷新向量索引，让刚写入的数据可以被检索。
3. `hybrid_search`：同时给出全文条件和向量条件，并用 `rank.rrf` 融合。

三条示例的全文条件必须写成 `query.where_document.$contains`。向量条件必须写成 `knn.query_embeddings`。融合参数必须写成 `rank.rrf`。不要改成别的字段名，也不要用单独的全文检索或向量检索代替这次混合检索。

向量使用示例里给出的三维显式数值。不要下载嵌入模型，不要调用推理接口，不要另行编造向量替换示例。

`examples/hybrid_search_calls.py` 只组装这三步的参数并打印，方便在没有数据库连接时核对调用形状。它不读取 `.env`，也不建立连接。真正执行时，只能使用调用方已经提供的 collection。没有可用 collection 时就停止并说明缺少连接，不要猜测主机、账号或密码。

## 2. 三条示例数据

示例只包含这三条。`id`、`document`、`embedding`、`metadata` 都要一起写入。

| id | document | embedding | metadata.topic |
| --- | --- | --- | --- |
| lab-seekdb | seekdb 同时保存文档和向量，用于混合检索实验 | [1.0, 0.0, 0.0] | retrieval |
| lab-engineering | 工程笔记记录 hybrid search 的全文与向量融合 | [0.9, 0.1, 0.0] | engineering |
| lab-workflow | 工作流知识库把文档和向量检索连在一起 | [0.0, 0.0, 1.0] | workflow |

相同内容在 `examples/three_records.json`。调用前先确认数组长度是 3。不是 3 条就停止，不要补数据，也不要删成更少。

## 3. 操作步骤

以下调用对应 pyseekdb 的 Collection 方法。集合需要已经按三维向量创建，距离度量与示例向量一致。不要为了跑通示例去删除集合、切换到其他库，或改写这三条以外的记录。

### 3.1 upsert

把三条记录一次写入。已存在的 `id` 会被更新，不存在的 `id` 会被插入。

```python
records = [
    {
        "id": "lab-seekdb",
        "document": "seekdb 同时保存文档和向量，用于混合检索实验",
        "embedding": [1.0, 0.0, 0.0],
        "metadata": {"topic": "retrieval"},
    },
    {
        "id": "lab-engineering",
        "document": "工程笔记记录 hybrid search 的全文与向量融合",
        "embedding": [0.9, 0.1, 0.0],
        "metadata": {"topic": "engineering"},
    },
    {
        "id": "lab-workflow",
        "document": "工作流知识库把文档和向量检索连在一起",
        "embedding": [0.0, 0.0, 1.0],
        "metadata": {"topic": "workflow"},
    },
]
assert len(records) == 3

collection.upsert(
    ids=[item["id"] for item in records],
    documents=[item["document"] for item in records],
    embeddings=[item["embedding"] for item in records],
    metadatas=[item["metadata"] for item in records],
)
```

写入后应按这 3 个 `id` 取回。数量不是 3 就不要进入下一步。

### 3.2 refresh_index

`upsert` 之后立刻调用，不要省略：

```python
collection.refresh_index()
```

这一步刷新异步向量索引任务。没有它，后续向量检索可能看不到刚写入的向量。不要用删除集合、重建库或手工改系统表来代替。

### 3.3 hybrid_search

使用第二条示例的向量作为查询向量，全文条件匹配文档中的“工程”。参数位置固定为：

- `query.where_document.$contains`
- `knn.query_embeddings`
- `rank.rrf`

```python
query_embedding = [0.9, 0.1, 0.0]
result = collection.hybrid_search(
    query={
        "where_document": {"$contains": "工程"},
        "n_results": 3,
    },
    knn={
        "query_embeddings": [query_embedding],
        "n_results": 3,
    },
    rank={"rrf": {}},
    n_results=3,
    include=["documents", "metadatas"],
)
```

参数含义：

- `query.where_document.$contains`：全文检索条件。这里的值是“工程”，用来命中第二条文档里的“工程笔记”。不要把它改成元数据过滤。
- `knn.query_embeddings`：向量检索的查询向量。外层是查询列表，本例只有一个三维向量 `[0.9, 0.1, 0.0]`。不要把三条文档向量一起塞进这个字段。
- `rank.rrf`：倒数排名融合。本例使用空对象 `{}`，表示按接口默认的 RRF 融合全文候选和向量候选。不要改成只按某一种分数排序。
- 两路 `n_results` 和最终 `n_results` 都设为 3，与示例条数一致。

## 4. 怎样读结果

`hybrid_search` 的返回与向量查询兼容。`ids` 是列表的列表；本例只有一组查询，读取 `ids[0]`。

回答时只引用本次返回里真实出现的 `id`、文档和元数据。返回不足 3 条时按实际条数说明，不要把示例表里没有返回的行补进命中列表。返回为空时直接说明没有命中，不要编造 `lab-seekdb`、`lab-engineering` 或 `lab-workflow`。

全文条件“工程”预期能覆盖 `lab-engineering` 的文档。查询向量 `[0.9, 0.1, 0.0]` 与 `lab-engineering` 的向量相同，也接近 `lab-seekdb`。最终名次以本次 `rank.rrf` 的返回顺序为准，不要在回答里写死名次。

## 5. 不要做的事

- 不要读取或打印 `.env`、数据库密码或 `MODELSCOPE_API_TOKEN`。
- 没有调用方已经提供的 collection 时，不要自己猜测连接信息。
- 不要删除集合，不要改写这三条示例以外的数据。
- 不要用单独的 `query` 或只做全文检索来代替 `hybrid_search`。
- 不要省略 `upsert` 之后的 `refresh_index`。
- 不要把 `$contains` 放到 `knn` 里，也不要把 `query_embeddings` 放到 `query.where_document` 里。
- 不要增加第 4 条示例，也不要删到少于 3 条。
- 不要在没有实际返回时声称检索成功。
