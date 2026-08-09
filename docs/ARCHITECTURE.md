# Architecture

## Boundary

V5 是独立项目。它只在运行时读取/升级用户指定的现有数据库；不会引用、覆盖或向 V4 源码目录写文件。

## Layers

1. **Launchers** — `admin_launcher.py` / `staff_launcher.py` 只负责模式选择和应用启动。
2. **UI** — Qt widgets 只处理展示与用户意图，不直接拼接 SQL。
3. **Services** — 销售、库存、采购、备份、打印等业务事务边界。
4. **Repositories** — 参数化 SQL、分页查询和持久化映射。
5. **Database** — 连接政策、schema、migration、integrity 与 transaction。

依赖方向固定为 `UI → Services → Repositories → Database`。打印发生在 sale commit 之后；打印失败绝不 rollback 已成功的销售。

## Data choices

- Money: SQLite `INTEGER`, 单位为 sen。
- Quantity: Python `Decimal`；SQLite 保存规范化 decimal text，并由 service 层验证。
- Time: SQLite 保存含时区 ISO-8601，UI 转换成本地时间。
- IDs: 内部 integer primary key；barcode、SKU 和业务单号都是可索引业务键，不作为 PK。
- Deletion: 历史关联对象优先 tombstone/anonymize；需要真正反向库存的 Sale/Purchase 删除由单一服务事务处理。

## Concurrency and durability

单机单收银台仍启用 SQLite WAL、foreign keys、busy timeout。关键写入使用 `BEGIN IMMEDIATE`，避免中途状态可见。

