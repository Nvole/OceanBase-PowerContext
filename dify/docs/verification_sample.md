# Dify 主链路验证样例

本样例只调用 Dify 的已发布 Workflow API。业务后端由 Dify 的 HTTP Request 节点访问，评审不需要直接调用业务后端接口。

## 前置条件

1. 按 `README.md` 完成 `.env`、seekdb 初始化和 Compose 启动。
2. 执行 `python scripts/import_dify.py --initialize-local`，脚本会导入并发布 `docs/absurd_debate.dsl.yml`，并把本机 Dify App API Key 保存到未提交的 `.runtime/app.json`。
3. 在 PowerShell 中读取本机 API Key：

   ```powershell
   $app = Get-Content .runtime/app.json | ConvertFrom-Json
   $headers = @{ Authorization = "Bearer $($app.api_key)" }
   ```

不需要 OpenAI、MiniMax 或其他模型服务密钥。本作品的“规则主持”是 Dify Code 节点，Dify 仍负责输入、节点编排、HTTP 检索、HTTP 写入和最终输出。

## 第一次运行

```powershell
$body = @{
  inputs = @{
    player = '验收样例玩家'
    motion = '猫应该交税吗'
    side = '正方'
    argument = '猫霸占窗台阳光却不交税！证人说"喵"。'
  }
  response_mode = 'blocking'
  user = '验收样例玩家'
} | ConvertTo-Json -Depth 6

$first = Invoke-RestMethod `
  -Uri http://127.0.0.1:15001/v1/workflows/run `
  -Method Post -Headers $headers -ContentType 'application/json' -Body $body
$first.data.outputs | ConvertTo-Json -Depth 8
```

预期结果：HTTP 200，`data.status` 为 `succeeded`，`data.total_steps` 至少为 7，输出包含：

- `fusion = seekdb_hybrid_rrf`，表示 Dify 已使用 seekdb 检索结果；
- `saved` 中包含本轮 `p_<round_id>` 和 `h_<round_id>` 两条记录；
- `card` 为规则主持生成的可读辩论卡片。

## 连续记忆验证

使用相同的 `player` 和 `motion` 再提交一轮，只把 `argument` 改为：

```text
我还要为刚才的阳光税申请退款，呼噜也算劳动！
```

仍然只调用上面的 `/v1/workflows/run`。第二次结果的 `retrieved_ids` 应包含第一次返回的 `p_<round_id>`，说明 Dify 的检索节点从 seekdb 读到了上一轮记录。重复提交第一次输入时，`saved.count` 不应重复增加，说明写入具有幂等性。

## 重启后验证

```powershell
python scripts/verify_dify.py --seekdb-host 127.0.0.1 --restart-backend
```

脚本会重新通过 Dify Workflow API 执行四轮，并检查节点执行轨迹、seekdb 中的记录和业务后端重启后的记忆复用。每轮的原始 Dify 响应和节点执行记录会写入 `evidence/`；这些文件只包含运行证据，不包含 API Key。

## 恢复初始状态

样例使用固定玩家名时，可换一个新的 `player` 值重新开始，不会影响已有记录。若要完全清空本地演示环境，先停止服务，再删除 Compose 数据卷，然后按 README 重新初始化：

```powershell
docker compose down -v
```

这会删除本机 Dify 元数据、Redis、插件和业务数据库中的演示数据，只应在评审环境需要完全重置时使用。
