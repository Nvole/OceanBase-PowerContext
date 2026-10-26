# 验证样例：发票日期范围

## 要改什么

给 `filter_invoices` 增加 `start_date` 和 `end_date`。区间是闭区间，按 `invoice_date` 的日历日比较。起止颠倒时返回空列表。

## 必须保持

金额闭区间、状态精确匹配、条件逻辑与、省略条件不筛选、原顺序、不修改入参。有效规格是资料库中的 `docs/*_spec.md` 命中文档，当前句子以 `SPEC_SENTENCE:` 开头。

## 初始数据

`data/invoices.json`：

| id | amount | status | invoice_date |
| --- | --- | --- | --- |
| A | 10 | open | 2024-01-01 |
| B | 50 | paid | 2024-02-15 |
| C | 80 | open | 2024-03-20 |
| D | 50 | void | 2024-02-15 |
| E | 50 | paid | 2024-03-01 |

## 上下文必须能定位

这些名字来自查询命中的 metadata，不是 CLI 里的固定清单：

- 规格：含 `SPEC_SENTENCE:` 的规格文档
- 代码：含 `def filter_invoices` 的代码文档
- 测试：含 `def test_filter_by_date_range` 的测试文档
- 状态：PowerContext 中带 `TRACK07_STATE_MARKER` 的记录；服务不可用时明确标 blocked

调用：

```sh
python -m sdd_context build --task "invoice-date-range filter_invoices test_filter_by_date_range SPEC_SENTENCE 日期范围 金额 状态"
```

## 预期

- 修改前：`test_filter_by_date_range` 等日期测试因未筛选日期而断言失败；金额和状态测试通过。日志是 `results/tests_before.txt`。
- 修改后：同一组测试全部通过。日志是 `results/tests_after.txt`。
- 2024-02-01 到 2024-02-28 得到 B、D。
- 同期再加 `min_amount=50` 和 `status=paid` 只得到 B。
- 把规格句子改掉并重新导入后，`build` 读到新句子；未导入前仍是旧句子。

## 重置

重跑 `tests/run_verification.py`。它会换回修改前快照记录失败，再恢复实现、重导资料，并清空后重写 PowerContext。
