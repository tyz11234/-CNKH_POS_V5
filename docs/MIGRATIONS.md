# Database migration plan

## Startup gate

已有数据库每次升级前执行：

1. 只读打开并运行 `PRAGMA integrity_check`。
2. 使用 SQLite backup API 创建带时间戳的完整副本。
3. 在 `BEGIN IMMEDIATE` 单一事务中执行尚未应用的 migrations。
4. 写入 `schema_migrations` 和 `PRAGMA user_version` 后 commit。
5. 任一步失败即 rollback，抛出 `DatabaseStartupError`，应用不得进入可写 UI。

## supplier_payments normalization

V5 检测旧表的实际列，而不假设某个 V4 schema。金额来源优先级：

1. `amount_cents`
2. `payment_cents`
3. `paid_cents`
4. `amount`（按 RM 转换为 sen，Decimal ROUND_HALF_UP）

所有行写入统一 `amount_cents INTEGER NOT NULL CHECK(amount_cents > 0)`。未识别的旧字段和原始值同时存入 `legacy_source_json`，便于核查；migration 事务完成前不会删除/覆盖源表。启动前 backup 是最终不可变恢复点。

## Version policy

Migration 只可向前、不可静默降级。应用版本低于数据库 schema 时拒绝启动。每个 migration 都必须有 old-schema fixture 测试。

