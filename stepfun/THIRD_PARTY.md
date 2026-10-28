# 第三方与模型资产

- Xenova/all-MiniLM-L6-v2：Apache-2.0；上游模型标注的来源/许可在固定模型 manifest 中。FP32、INT8 ONNX 和 tokenizer 均从同一固定 revision 获取，未自行训练或改名伪造量化文件。`licenses/model-Apache-2.0.txt` 为完整 Apache 2.0 文本，`docs/upstream-model-README.md` 保留模型原始说明。
- @huggingface/transformers 3.8.1：Apache-2.0，完整许可证在 `licenses/transformers-Apache-2.0.txt`。
- ONNX Runtime Web 1.22.0-dev.20250409-89f8206ba4 / ONNX Runtime：MIT，完整许可证在 `licenses/onnxruntime-MIT.txt`；上游第三方通知在 `licenses/onnxruntime-ThirdPartyNotices.txt`。
- seekdb-js（npm seekdb）1.4.0：Apache-2.0；安装依赖时保留包内许可证，完整依赖与解析版本见 package-lock.json。
- esbuild / Playwright 仅用于构建/验证，按各自软件包附带的许可证使用。不把 node_modules 或本机数据库凭据打包。

此项目源码未自行添加未经用户授权的版权或许可证头；使用/再分发第三方模型和运行时需遵守上述各自许可。
