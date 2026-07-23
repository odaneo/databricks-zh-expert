# 阶段 9 固定评估归档

本目录保存阶段 9 最终基线使用的两份固定数据集：

- `workspace_context.yml`
- `end_to_end.yml`

对应的真实双模型运行结果保存在：

```text
.local/evaluations/stage9-final-v2-20260720/
```

这些文件只用于历史复现和阶段 9/10 纵向比较，不再作为默认评估输入。当前评估继续读取
`tests/evals/workspace_context.yml` 和 `tests/evals/end_to_end.yml`。

不得修改本目录中的归档数据集，也不得用阶段 10 的 Workspace Unit ID、数据集版本或 Hash 覆盖它们。
