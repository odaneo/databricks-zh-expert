from fastapi import Request

from databricks_zh_expert.core.config import Settings


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings
