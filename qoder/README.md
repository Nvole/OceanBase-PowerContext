# 科研资料检索助手

基于 seekdb 的 Markdown/TXT 科研资料检索工具。支持阅读笔记、实验记录、待办导入，关键词/类型/标签筛选，匹配段落、详情、同名保留和删除。

## 当前状态（2026-10-28）

- 43 项 pytest 全部通过：原 15 项 + Qoder 新增 28 项回归；统一临时 SQLite 隔离执行，不清理业务库。
- 19 项真实 Chromium/seekdb 检查全过，包含 seekdb 服务重启后持久化。证据 `submission/release_20261028/browser_acceptance.json`，时间 2026-10-28 20:57:34 +08:00；版本 `5.7.25-OceanBase seekdb-v1.4.0.0`，独立库 `qoder_research`。
- 测试资料已清理，原有资料保留。截图 01 至 06 同目录；第 06 张仅为最后文案更新前的本地展示预览，不是公开网址。
- Qoder Sites 已公开发布：`https://research-notes-seekdb-bahxdw2dd6h.qoder.zone`；Qoder UID：`01a17cd3-c034-70da-a674-bacbcc8faa16`。GitHub 提交见仓库分支与 commit 记录。

## 快速开始

Python 3.10+（实际使用 3.13）：

```bash
python -m pip install -r requirements.txt
python scripts/run.py --sqlite --import-examples
```

打开 `http://127.0.0.1:8000`。SQLite 文件位于 data 下，也可通过进程环境变量 `QODER_SQLITE_PATH` 指定，自动创建父目录。

### 使用自己的 seekdb

先创建独立数据库 `qoder_research`。自行创建 `.local/connection.json`，不得提交真实凭据：

```json
{"host":"YOUR_SEEKDB_HOST","port":2881,"user":"YOUR_USER","password":"YOUR_PASSWORD"}
```

```bash
python scripts/run.py --connection-file .local/connection.json --import-examples
```

启动器固定使用 `qoder_research`；仅显式参数读取连接文件，不打印密码。也可设置进程环境变量 `SEEKDB_HOST/SEEKDB_PORT/SEEKDB_USER/SEEKDB_PASSWORD/SEEKDB_DATABASE`。项目不自动加载 `.env`，仅复制 `.env.example` 不生效。禁止操作 `competition_practice` 或其他项目数据。

## 复现验收

```bash
python -m pytest tests -q -p no:cacheprovider
```

所有测试强制临时 SQLite 并核查路径隔离。交付包附实际日志；此前实测 `43 passed, 1 warning in 2.07s`，warning 为 TestClient/httpx 弃用提示，并非失败。

可选浏览器验收（Chromium 安装需联网）：

```bash
python -m pip install -r requirements-validation.txt
python -m playwright install chromium
python scripts/verify_release.py
python scripts/verify_release.py --connection-file .local/connection.json
```

默认临时 SQLite，显式连接文件才访问真实 seekdb。`--restart-wsl-seekdb` 会重启特定本机 WSL 服务，仅在对应环境并明确接受重启时使用。

19 项验收覆盖服务健康、真实后端、三类上传、检索、类型/标签/中文筛选、详情、同名保留、XSS、元数据拒绝、SQL 注入、删除、无 JS 错误、重启前记录/服务重启/重启后持久化及本地展示预览。

## 技术与安全边界

- FastAPI + SQLAlchemy + PyMySQL；seekdb 使用 MySQL 协议，SQLite 为本地回退。
- 参数化 LIKE 子串匹配，不是向量/混合检索或全文分词；关键词和标签通配符按字面转义。
- doc_type 仅 reading/experiment/todo，前端 HTML 转义；仅 UTF-8 `.md/.txt`，文件上限 5MB。
- 同名资料独立 ID，不覆盖。公开 Sites 仅静态作品展示，FastAPI/数据库需本地独立运行，不声称在线业务服务。
- 样例是合成内容，未测量用户提效或访问量。不交付真实数据库、密码、token、缓存、私有报名仓库或其他赛题源码。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| POST | `/api/documents/upload` | 上传 |
| GET | `/api/documents/search?keyword=...` | 搜索筛选 |
| GET | `/api/documents/{id}` | 详情 |
| DELETE | `/api/documents/{id}` | 删除 |
| GET | `/api/documents/` | 列表 |

## 目录与开发分工

`app/` 后端，`static/`/`templates/` 前端，`examples/` 合成资料，`tests/` 测试，`scripts/run.py` 启动，`scripts/verify_release.py` 验收，`site/index.html` 展示页。

- Qoder（2026-10-27）：schema、API、前端、样例和原 15 项测试。
- Qoder（2026-10-28）：新增 28 项回归测试、文档、展示页、连接重启恢复、安全测试隔离、元数据/标签防护及 19 项真实浏览器/seekdb 验收。

历史见 DEVLOG。GitHub 仓库为 `https://github.com/Nvole/OceanBase-PowerContext`，提交分支为 `2026-competition-ecosystem`。
