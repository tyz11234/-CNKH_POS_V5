# Database migration plan

## Startup gate

已有数据库每次升级前执行：

1. 只读打开并运行 `PRAGMA integrity_check`。
2. 读取 `PRAGMA user_version`；只有 schema 低于目标版本时，才使用 SQLite backup API 创建带时间戳的完整副本。
3. 在 `BEGIN IMMEDIATE` 单一事务中执行尚未应用的 migrations。
4. 写入 `schema_migrations` 和 `PRAGMA user_version` 后 commit。
5. 任一步失败即 rollback，抛出 `DatabaseStartupError`，应用不得进入可写 UI。

目标 schema 为 **7**。Migration 7 新增：

- `supplier_products`：供应商与商品多对多目录。
- `daily_cash_closings.opening_cash_cents`：开档现金。
- `sale_returns.refund_method`：Cash/Card/DuitNow/Credit adjustment 退款方式。
- `5.0.0-alpha.4` 应用版本记录。

`pre_migration` 与其他备份统一只保留最近 30 份。最新 schema 再次启动不会重复产生 migration 备份。

## supplier_payments normalization

V5 检测旧表的实际列，而不假设某个 V4 schema。金额来源优先级：

1. `amount_cents`
2. `payment_cents`
3. `paid_cents`
4. `amount`（按 RM 转换为 sen，Decimal ROUND_HALF_UP）

所有行写入统一 `amount_cents INTEGER NOT NULL CHECK(amount_cents > 0)`。未识别的旧字段和原始值同时存入 `legacy_source_json`，便于核查；migration 事务完成前不会删除/覆盖源表。启动前 backup 是最终不可变恢复点。

## Version policy

Migration 只可向前、不可静默降级。应用版本低于数据库 schema 时拒绝启动。每个 migration 都必须有 old-schema fixture 测试。当前自动测试覆盖 fresh schema 7、schema 6→7，以及已是 schema 7 时不重复备份；未由 fixture 覆盖的未知 V4 变体不能宣称已兼容。
