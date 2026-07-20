# Northwind 上游来源

本目录归档 `pthom/northwind_psql` 的 PostgreSQL Northwind 示例数据库原件，用于建立可复现的项目 Workspace。

## 固定版本

- 仓库：https://github.com/pthom/northwind_psql
- 原始文件：https://raw.githubusercontent.com/pthom/northwind_psql/cd0ef28d66369fbe177778e604e4be0f153c9e5c/northwind.sql
- Commit：`cd0ef28d66369fbe177778e604e4be0f153c9e5c`
- SHA-256：`0EE30C01BA282F7194F38BF7F99CD6BE0470B7EE5F67D0F7CA41FB058D735E0C`
- 许可证：Microsoft Public License，原文见 `LICENSE.northwind`

## 文件职责

`upstream/northwind.sql` 是未经改写的上游原件，只用于来源核验和重新提取，不会注册为 Workspace Source，也不会发送给模型。

`.databricks-expert/source-schema/northwind-schema.sql` 是确定性派生文件，只保留 14 条 `CREATE TABLE`、14 条主键约束和 13 条外键约束。它不包含 `DROP TABLE`、`SET`、`INSERT`、样例数据或运行环境配置。

## 更新规则

升级上游版本时必须固定新的 commit，重新核对原件 Hash、许可证和提取差异。原件与派生文件应分别评审；禁止直接编辑原件，也禁止为了评估题增加源 Schema 中不存在的字段。
