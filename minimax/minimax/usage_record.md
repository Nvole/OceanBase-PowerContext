# MiniMax 使用记录

- 状态：blocked
- 是否实际参与：False
- 模型：MiniMax-M2.5
- 接口：https://api.minimax.io/v1/text/chatcompletion_v2
- 原因：MINIMAX_API_KEY is unset. No dialogue was fabricated.

日期范围代码是在记录修改前失败日志之后，于仓库内按规格补上的。
没有 MINIMAX_API_KEY，因此没有编造助手回复。
若之后设置该环境变量，`sdd_context.minimax_assistant.request_change` 会把查询到的上下文发给 MiniMax。

## 本次上下文

任务、查询命中和来源见 `results/context.json` 与 `results/db_query_record.json`。
规格句子更新前后见 `results/spec_refresh.json`。
PowerContext：{"status": "reused", "version": "1.4.0", "url": "http://127.0.0.1:18617", "saved": {"status": "saved", "http_status": 200, "body_keys": ["changed", "records"]}, "restart": {"started": true, "status": "running", "ready": {"status": "ready", "checks": {"runtime": "ready", "database": "ready", "artifact_processing_supervisor": "disabled", "access_mode": "disabled", "authentication_provider": "disabled", "access_provider": "disabled", "access_resource_kinds": "server,scope,artifact", "access_artifact_families": "atomic-memory:enabled,experience:enabled,handoff:enabled,memory:enabled,profile:enabled,prompt:enabled,skill:enabled"}}}, "show_state_status": "ready", "used_in_context": true}
