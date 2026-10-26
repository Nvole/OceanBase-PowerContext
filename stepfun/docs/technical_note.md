# 技术说明：浏览器端向量化与 seekdb 混合检索

## 模型与量化

模型来源是 Apache-2.0 的 `sentence-transformers/all-MiniLM-L6-v2`，浏览器加载其 Transformers.js 转换版 `Xenova/all-MiniLM-L6-v2`（Hugging Face `main`）。维度 384，mean pooling，L2 归一化。运行库是 `@huggingface/transformers@3.7.2`。

量化使用 INT8。Worker 固定 `dtype: 'q8'`，文件名后缀 `_quantized`，即 `onnx/model_quantized.onnx`。它和 `onnx/model_int8.onnx` 是同一 LFS 对象。WebGPU 路径也显式使用 q8，避免该运行库在未指定 dtype 时退回 FP32。

体积口径只比较 ONNX 权重，不含共用的 tokenizer 和 config。2026-10-26 的 Hugging Face tree API：FP32 `onnx/model.onnx` 为 90387606 字节，INT8 为 22972370 字节，压缩比 3.9346。`model_int8.onnx` 与量化文件字节数相同。测试时 A6000 再次请求该 API 失败（URLError），因此结果沿用这份快照，没有把权重大于 20MB 的文件下载到服务器。FP16 文件为 45297825 字节，本应用不使用。

INT8 与 FP32 的语义检索质量没有在这台无头机器上测量，这里不写 Recall 或 nDCG。页面上的“固定问题”按钮只统计当前浏览器、当前 INT8 后端刚刚跑出的 Hit@3。

## 端侧运行

文档向量和查询向量都在 Web Worker 中计算。设备选择顺序是：有 `navigator.gpu` 且 `requestAdapter()` 成功时用 WebGPU，否则用 WASM；WebGPU 初始化失败再降级到 WASM。页面徽章显示实际后端，不显示仅仅“希望使用”的后端。WASM 线程数设为 1，因此不需要跨源隔离头，模型仍可从 Hugging Face 下载。没有调用云端推理 API。

批大小为 8。用户按下实测按钮后，页面比较批处理和逐条编码，数字只来自那一次运行。

## seekdb

集合名 `track02_stepfun_kb`，库 `track02_stepfun`。HNSW，384 维，cosine，全文分析器 IK。创建和读取都传入 `embedding_function=None`。

写入调用 `upsert`，随后 `refresh_index`。混合检索只有这一条数据库调用：

```python
collection.hybrid_search(
    query={'where_document': {'$contains': text}, 'n_results': n},
    knn={'query_embeddings': [vector], 'n_results': n},
    rank={'rrf': {}},
    n_results=n,
    include=['documents', 'metadatas', 'distances'],
)
```

服务拒绝缺少 `embedding` 的请求，也拒绝 `query_texts`，避免 pyseekdb 在服务端补向量。同一 id 再次 upsert 覆盖旧行。`metadata.session_id` 可同时加到全文和向量两路过滤上。

## 状态、优化与实测边界

集合在服务端只有 `track02_stepfun_kb`。浏览器把会话号放进 sessionStorage 和元数据。清空集合会删除后按同样配置重建，embedding function 仍为空。

已做的优化是浏览器批编码、模型缓存、整批写入后只刷新一次索引，以及服务端不加载模型。固定向量测试使用单位向量，验证关键词与向量一致时命中对应文档、两路不一致时两篇都进入结果、过滤不串角色、刷新后新文档可检索、重复 id 不增行。

2026-10-26 在 A6000 上对 seekdb 1.4.0.0 的实测：6 条夹具批量 upsert 228 ms；首次 `refresh_index` 514 ms，紧接着再刷 202 ms；增量写入后的刷新 602 ms。刷新前新文档检索不到，刷新后排第一。预热后 7 次 `hybrid_search` 的原始耗时中位数是 2.62 ms，第一次冷查询是 138 ms。中文 `$contains`「刷新索引」命中了对应文档。这些数字都在 `results/fixed_vector_test.json`。

`webgpu_ms` 和 `wasm_ms` 为 null。无头环境没有浏览器计时，不编造 WebGPU 或 WASM 的毫秒数。量化前后的语义质量也没有在这里运行。
