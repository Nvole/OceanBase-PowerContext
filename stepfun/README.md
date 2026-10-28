# StepFun：端侧 Embedding + seekdb 混合检索

题号 **800510**。完整文档/查询向量化都在浏览器 Worker 中执行，不调用云端/Node embedding。Node 仅做本机 HTTP 网关，调用 **seekdb-js 1.4.0** 写入真实 seekdb 并执行数据库混合检索。

## 1. 启动（已有 seekdb 不要重复部署）

前提：Node >=22、Python >=3.9、现代 Chrome/Edge；本地 seekdb server（本机实测 1.4.0.0），账号能创建 `stepfun_` 专用库。只支持本机演示，不要公开无认证服务。

```powershell
cd stepfun
npm.cmd ci --ignore-scripts --no-audit --no-fund
Copy-Item .env.example .env
# 在本机编辑 .env 的数据库账号/密码，绝对不要提交 .env
npm.cmd run models
npm.cmd run build
npm.cmd start
```

浏览器打开 `http://127.0.0.1:8010`（不要改用 localhost 访问，否则 Host 校验拒绝）。ZIP 已带模型和 dist：模型获取会先校验 SHA256，文件完整时不联网下载；已有依赖后可完全离线推理。Git 提交默认不包含 models/dist，评审从源码运行时执行上述命令重建。

`.npmrc` 的 `legacy-peer-deps=true` 避免安装不用的服务端 embedding peer；`--ignore-scripts` 不启用 onnxruntime-node 原生推理。浏览器运行时在构建时复制到本地，CSP 禁止外部模型/推理网络请求。

已有本机 `.seekdb-local/connection.json` 的 Windows 环境可运行 `powershell -File scripts/start-local.ps1`；此脚本只在进程中加载现有凭据，不复制配置、不初始化旧数据库。若 WSL 退出造成连接拒绝，先保持 WSL 会话运行再启动应用。

## 2. 没有数据库时的可选启动

优先复用队友已有的 seekdb。不允许使用普通 MySQL 或内存列表替代。可选 Docker 方式见 `scripts/start-seekdb.ps1`：仅绑定 `127.0.0.1:2881`，命名卷持久化。脚本若同名容器已存在只启动，不删除数据。

```powershell
powershell -File scripts/start-seekdb.ps1
```

Docker 示例依据官方 seekdb README；本机真实验证用的是已有 WSL server，不是该 Docker 方案。默认镜像为 `oceanbase/seekdb:latest`，会随上游变化；严格复现应通过 `-Image` 指定队友已验证的 1.4.0.0 镜像 digest。数据库设置完成后在 `.env` 中填实际密码，等待 server ready。

## 3. 演示

1. 设置小写集合名；默认 INT8/q8、batch1、WebGPU 优先、批量一次刷新。
2. 点击“载入固定英语语料”，或上传 `.txt/.md` / 粘贴文本，点击“本地向量化并导入”。
3. 输入英语问题，点击“查询”：展示排名、seekdb 融合 score、标题与原文。
4. 切 FP32/q8 自动对应不同数据库集合；切集合后结果清空，需在当前集合/精度导入再查询。配置保存于 localStorage。
5. 连续导入同名文件，同一块使用标题 SHA256 + chunk 序号稳定 upsert；新文件增量保留。此版无删除/按文件缩短后自动删除旧尾块功能；要完全替换知识库请用新集合。

文本按段落、900 字符上限/700 字符步长切块；单次 <=200 块，文件 <=1MB。长文本仍受模型 tokenizer 上下文限制，本版英语模型，不声明中文质量。

### WebGPU 真实性边界

Worker 显式 `device:'webgpu'`，不可用、初始化/执行失败自动 WASM；界面始终显示实际后端与原因。INT8 在不同 GPU 内核上可能数值异常：首次在浏览器用 3 条固定独立探针比较同一 q8 模型的 GPU 与 WASM 向量，全部余弦 >=0.99 才允许 GPU，否则释放 GPU 会话并使用 WASM。**本机 AMD RDNA-2 的 q8 路径自检失败，因此最终 INT8 实测后端是 WASM；FP32 WebGPU 是真实硬件执行。**守卫不是修复上游 GPU 内核，不宣称已获得 INT8 GPU 加速。

## 4. 真实验证与报告

保持应用运行，在另一终端执行：

```powershell
npm.cmd test
npm.cmd run verify
npm.cmd run verify:refresh
# 先停止并重新 npm.cmd start，再执行：
npm.cmd run verify:persistence
npm.cmd run inspect
npm.cmd run report
```

`verify` 使用已安装的 Edge 无头模式，无 mock 向量，四次每配置（首次 + 三次后续），含 18 文档/12 查询、FP32/INT8、WASM/WebGPU、batch1/8；测试文件上传、幂等/增量、集合/精度隔离、XSS、页面刷新、Origin/非法载荷与真实自动降级。可用 `EDGE_PATH` 指定 Chrome/Edge 可执行文件；否则 Windows 默认 Edge 安装路径，Linux 使用 Playwright 默认浏览器（需自行安装）。`APP_URL` 默认固定 127.0.0.1:8010。

`verify:refresh` 固定相同集合和真实浏览器向量，写批大小始终为1，只改变刷新频率，预热后各3次取中位数。`verify:persistence` 需实际重启应用服务，不重启数据库；不虚报数据库进程重启测试。`inspect` 将真实 `SHOW CREATE TABLE` 与 `SHOW INDEX` 导出，不输出凭据。

结果：`TECHNICAL_NOTE.md` 是一页技术说明；`PERFORMANCE_REPORT.md` 有完整方法与结果；`evidence/` 有原始值、请求、真实 DDL、失败预检及截图。质量指标是自编小样本的工程验收结果，不能外推大规模/中文质量，也不是比赛平台分数。

## 5. 数据库与安全

- 仅允许数据库名以 `stepfun_` 开头；不修改原比赛库，应用不执行 DROP。
- 通过 SDK schema 创建 `FULLTEXT(space)` 和 `HNSW(dimension=384,distance=cosine)`；元数据含 title/model/dtype。
- `hybridSearch` 使用 query text + browser embedding，数据库 `DBMS_HYBRID_SEARCH` 执行 RRF（rankConstant=60、rankWindowSize=50）。没有在客户端分路融合。
- 单个全局串行队列保护 SDK `SET @search_parm` / SQL 的会话一致性，代价是本机并发吞吐有限。
- 只监听回环地址；Host/Origin 校验、CSP、COOP/COEP、8MB API 请求上限；结果使用 textContent，不执行导入 HTML。
- 不上传 `.env`、connection.json、数据库文件或 node_modules；ZIP 包含模型仅便于本地运行。大规模部署、认证/权限、多用户、多语言、图片不是本次实现范围。

## 6. 模型、复现与提交

模型源：Xenova/all-MiniLM-L6-v2；完整 revision 与固定 SHA256 在 `model-manifest.json` 和 `scripts/download_models.py`。直接取得上游公开 FP32 和动态 8-bit ONNX；未自行训练。许可证在 `licenses/`，运行时第三方说明见 `THIRD_PARTY.md`。

如网络要求代理，请只在本机为下载命令配置 `HTTPS_PROXY`，不要把代理/密码写入项目。下载器标准库实现流式下载、三次重试、临时文件原子替换、精确字节与固定 SHA256 校验；已存在文件也校验哈希。

队友在 **oceanbase/powercontext 的 2026-competition-ecosystem 基线**中放置本 `stepfun/`，由其合法比赛仓库执行 Git add/commit/push 并在平台填写对应分支/commit。此包没有创建仓库、上传 GitHub或获取平台评测回执。上传细节见 ZIP 顶层 `00_队友先读.md`。规则采用 2026-10-26 官方题面本地快照；当前语雀页面无法读取，未宣称再次实时核验。
