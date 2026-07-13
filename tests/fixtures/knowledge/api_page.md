# Create a new job

Creates a Databricks job containing one or more workflow tasks.

## Request

`POST /api/2.2/jobs/create`

| Field | Type | Description |
| --- | --- | --- |
| name | string | Human-readable job name |
| tasks | array | Workflow task definitions |

```json
{
  "name": "daily-sales",
  "tasks": []
}
```

## Response

Returns the identifier of the newly created job.
