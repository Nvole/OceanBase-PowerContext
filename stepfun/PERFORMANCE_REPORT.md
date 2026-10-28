# StepFun 实测报告

## 固定条件
- 测试时间：2026-10-28T14:00:47.264Z；CPU：AMD Ryzen 9 8945HX with Radeon Graphics        ；逻辑核心：32；内存：31.30 GiB。
- 浏览器 Edge 156.0.4314.42，Windows win32 10.0.26200；Node v24.15.0；5.7.25-OceanBase seekdb-v1.4.0.0。
- 浏览器 Worker：Transformers.js 3.8.1；ONNX Runtime Web 1.22.0-dev.20250409-89f8206ba4；WASM 固定 4 线程。GPU 实际适配器：AMD / RDNA-2，software=false，不是 NVIDIA。
- 数据：固定 18 条自编英语文档 / 12 个查询，二元人工相关性标签见 data/qrels.json。包含无关主题干扰文档；不代表大规模或中文检索能力。标签未随结果修改。
- 每配置 1 次首次请求 + 3 次后续重复；表中推理/写入/刷新为三次中位数，查询为 3×12 次的中位数，质量为其均值。未选择最快一次。

## 模型与量化
- 模型 Xenova/all-MiniLM-L6-v2，固定完整 revision 751bff37182d3f1213fa05d7196b954e230abad9，Apache-2.0。直接使用公开已量化 ONNX，未宣称重新训练/执行了离线量化。model_quantized.onnx 是上游 8-bit INT8 路径，与 FP32 共享同一 tokenizer/config。
- 纯模型：FP32 90387606 B；INT8 22972370 B；压缩比 3.9346×。
- 包含共同 tokenizer/config/vocab 的运行资产：FP32 91331916 B；INT8 23916680 B；压缩比 3.82×。许可证和说明文档不计入模型字节。逐文件 SHA256 见 model-manifest.json。

## 真实浏览器 + seekdb 结果
| 精度 | 请求→实际后端 | batch | 文档推理 ms | 文档/s | 查询推理 ms | DB ms | 查询端到端 ms | Recall@5 | nDCG@5 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fp32 | wasm→wasm | 1 | 489.39 | 36.78 | 9.51 | 9.02 | 24.18 | 0.9167 | 0.9167 |
| fp32 | wasm→wasm | 8 | 496.33 | 36.27 | 9.75 | 9.14 | 24.58 | 0.9167 | 0.9167 |
| q8 | wasm→wasm | 1 | 444.45 | 40.50 | 9.35 | 8.82 | 23.43 | 0.9167 | 0.9167 |
| q8 | wasm→wasm | 8 | 363.78 | 49.48 | 9.30 | 8.82 | 23.60 | 0.9167 | 0.9167 |
| fp32 | webgpu→webgpu | 8 | 274.50 | 65.57 | 16.33 | 9.12 | 31.57 | 0.9167 | 0.9167 |
| q8 | webgpu→wasm | 8 | 376.48 | 47.81 | 9.85 | 9.18 | 25.28 | 0.9167 | 0.9167 |

## 首次/加载与计时口径
| 精度/请求后端/batch | 首次模型准备 ms | 首次文档推理 ms |
|---|---:|---:|
| fp32/wasm/1 | 3731.27 | 760.83 |
| fp32/wasm/8 | 0.01 | 485.01 |
| q8/wasm/1 | 784.68 | 467.05 |
| q8/wasm/8 | 0.00 | 369.01 |
| fp32/webgpu/8 | 934.28 | 1544.95 |
| q8/webgpu/8 | 1048.13 | 359.47 |

- 模型准备包含从本机 HTTP 读取、模型初始化，以及 q8 WebGPU 独立探针数值自检。batch 切换复用同一会话，因此该行不是新的冷加载。
- 文档推理不含模型准备、写库和刷新；查询端到端从浏览器提交开始，含 Worker/查询向量化、HTTP、数据库和 DOM 渲染操作，不含屏幕实际合成时间。
- Worker performance resource 条目保存本机模型读取 duration/transferSize；外网一次性下载由脚本完成，不当成浏览器优化收益。
- 写入与刷新原始阶段值、首次/重复值、每个查询排名均在 evidence/browser-results.json。

## 单变量对比与选择
- 同为 WASM / batch1，FP32→INT8：文档推理 489.39→444.45 ms，1.10×；Recall 变化 0.00，nDCG 变化 0.00。
- 同为 FP32 / batch8，WASM→webgpu：496.33→274.50 ms，1.81×。
- batch1/8 不是必然提升：短语料 padding、设备和内核开销会抵消并行收益。本机 INT8 优先 batch1，不把多项改动混称一项优化。

## 刷新策略受控实验
保持相同集合、相同真实浏览器向量、writeBatchSize=1 不变，交替两种刷新策略；首对为预热，其后各 3 次取中位数。只改变刷新频率，不改变写入批大小。

| 策略 | 刷新调用次数 | 写入 ms | 刷新 ms | DB 导入总耗时 ms |
|---|---:|---:|---:|---:|
| each | 18 | 144.04 | 10903.14 | 11045.94 |
| batch | 1 | 110.34 | 492.47 | 605.12 |

## WebGPU 质量异常与安全降级
- 原始未加守卫的真实结果保存在 evidence/preflight-ungated-webgpu.json，不是最终性能结果。本机 q8/WebGPU 明显失真，未宣称成功。
- 最终 Worker 使用 3 条独立固定探针，对同一 q8 模型的 GPU/WASM 向量算余弦，每条至少 0.99 才允许 GPU；这不是用评测标签选结果，也不是服务端向量。异常自动释放 GPU 会话并使用 WASM，UI 显示实际后端和原因。
- 最终 q8/WebGPU-preferred 实际是 WASM，不能当作 INT8 GPU 加速成绩。FP32 WebGPU 是真实硬件路径。
- 启动第二个禁用 WebGPU 的 Edge，自动降级并完成真实数据库查询：检索完成：2 条，backend=wasm；自动降级：No WebGPU adapter。

## 功能验收
- quantizationQualityGate: PASS
- idempotentUpsert: PASS
- incrementalVisibility: PASS
- collectionIsolation: PASS
- precisionIsolation: PASS
- xssEscaped: PASS
- pageReload: PASS
- fileUploadUiAndStableUnicodeIds: PASS
- originAndMalformedPayload: PASS
- invalidVectorRejected: PASS
- noExternalNetwork: PASS
- automaticFallback: PASS
- 应用服务停止并重新启动后，以全新浏览器重新生成查询向量并查到原有数据：PASS。数据库进程未重启，不扩大此项结论。
- 实际表结构及全文/HNSW 索引：evidence/database-schema.json；所有数据仅位于 stepfun_ 专用库。

## 交付边界
- 18 hand-authored English documents / 12 queries only; no large-scale, multilingual or statistical significance claim
- GPU adapter selected by headless Edge is AMD RDNA-2 hardware, not the installed NVIDIA GPU
- INT8 WebGPU failed numeric consistency on this runtime/device and is automatically rejected; final INT8 GPU-preferred runs actually use WASM
- No GitHub push or competition scoring receipt
- Docker convenience deployment was not used or validated locally; actual DB is WSL seekdb 1.4.0.0
- 完整真实验证不等于已取得比赛分数。队友仍须在规定基线上提交分支/commit 并获取平台回执。
