from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        details: Any | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class KnowledgeIndexNotReadyAppError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="knowledge_index_not_ready",
            message="预置 Databricks 知识库尚未就绪。",
            status_code=503,
        )


class KnowledgeContextNotFoundAppError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="knowledge_context_not_found",
            message="没有找到足够相关的 Databricks 官方资料。",
            status_code=404,
        )


class ExpertProfileNotFoundAppError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="expert_profile_not_found",
            message="专家配置不存在。",
            status_code=422,
        )


class ExpertTemplateIndexNotReadyAppError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="expert_template_index_not_ready",
            message="专家模板索引尚未就绪。",
            status_code=503,
        )


class ExpertTemplateContextNotFoundAppError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="expert_template_context_not_found",
            message="没有找到可用的专家模板上下文。",
            status_code=404,
        )


class WorkspaceNotFoundAppError(AppError):
    def __init__(self, *, status_code: int = 422) -> None:
        super().__init__(
            code="workspace_not_found",
            message="项目工作区不存在。",
            status_code=status_code,
        )


class EmbeddingNotConfiguredAppError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="embedding_not_configured",
            message="知识检索所需的 OpenAI Embedding 尚未配置。",
            status_code=503,
        )


class EmbeddingRequestFailedAppError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="embedding_request_failed",
            message="知识检索向量生成失败，请稍后重试。",
            status_code=502,
        )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, error: AppError) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=error.status_code,
            content={
                "code": error.code,
                "message": error.message,
                "details": jsonable_encoder(error.details),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "请求参数不合法。",
                "details": jsonable_encoder(error.errors()),
            },
        )
