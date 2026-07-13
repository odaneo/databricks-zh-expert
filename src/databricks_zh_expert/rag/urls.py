from urllib.parse import urlsplit


class UnsafeOfficialUrlError(ValueError):
    pass


def validate_official_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https":
        raise UnsafeOfficialUrlError("Databricks URL 必须使用 HTTPS。")
    if parsed.hostname != "docs.databricks.com":
        raise UnsafeOfficialUrlError("Databricks URL 必须属于 docs.databricks.com。")
    if parsed.username is not None or parsed.password is not None or parsed.port is not None:
        raise UnsafeOfficialUrlError("Databricks URL 不能包含凭据或自定义端口。")
    if parsed.query or parsed.fragment:
        raise UnsafeOfficialUrlError("Databricks URL 不能包含 query 或 fragment。")
    return value
