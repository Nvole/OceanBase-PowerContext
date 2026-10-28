# StepFun 一页技术说明

**方案**：HTML/JS + Web Worker；文档和查询均由 Transformers.js 3.8.1 / ORT Web 在浏览器推理。Node 无 embedding 模型调用，只接收 384 维归一化向量，通过 seekdb-js 1.4.0 存储并检索。

**模型/量化**：Xenova/all-MiniLM-L6-v2，Apache-2.0，revision 751bff37182d3f1213fa05d7196b954e230abad9；采用上游公开 INT8 ONNX，mean pooling + L2 normalize。FP32 90387606 B → INT8 22972370 B，3.9346×；共同 tokenizer 计入后 3.82×。来源、字节与 SHA256 见 model-manifest.json / 下载脚本。

**固定实测**：AMD Ryzen 9 8945HX with Radeon Graphics        ；Edge 156.0.4314.42；seekdb 1.4.0.0；18 条自编英语文档、12 个查询、人工二元标签；首次单列，后续各 3 次取中位数。

| 配置（实际后端） | 文档推理 ms | DB 检索 ms | 端到端查询 ms | Recall@5 / nDCG@5 |
|---|---:|---:|---:|---|
| fp32/wasm/b1 | 489.39 | 9.02 | 24.18 | 0.9167 / 0.9167 |
| q8/wasm/b1 | 444.45 | 8.82 | 23.43 | 0.9167 / 0.9167 |
| fp32/webgpu/b8 | 274.50 | 9.12 | 31.57 | 0.9167 / 0.9167 |

**后端/质量**：优先 WebGPU。实际 FP32 GPU 适配器为 AMD RDNA-2；本机 INT8 WebGPU 数值自检失败，明确降 WASM，不虚报 GPU 加速。禁用 GPU 的 Edge 自动降级端到端已通过。INT8/WASM 对 FP32/WASM 质量变化：Recall 0.00、nDCG 0.00。

**seekdb/状态**：SDK 创建全文 space + HNSW/cosine/384 索引；hybridSearch 将文本和向量交给数据库 RRF（k=60，window=50），无客户端融合。upsert 稳定 ID，fp32/q8 分集合；串行数据库会话避免 SDK 会话变量污染。真实通过：幂等/增量可见、集合/精度隔离、页面刷新与应用重启持久性、XSS/Origin 拦截。

**优化/边界**：保持 WASM/batch1，INT8 文档推理 1.10×；刷新受控实验固定逐条写入，逐条刷新 11045.94 ms → 一次刷新 605.12 ms。batch 并非总更快；界面默认 INT8/batch1。18/12 是小样本工程验收，不能推断大规模/中文质量。原始值、失败预检、网络请求与截图在 evidence/；GitHub 上传与平台提测由队友完成。
