"""AppError hierarchy + global handlers producing the error envelope (decision #13).

Every error the API emits looks like:
    {"error": {"code": "<machine-readable>", "message": "<human-readable>"}}
including reshaped 422 validation errors.
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Base class for all deliberate API errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        self.message = message
        if code is not None:
            self.code = code
        super().__init__(message)

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content={"error": {"code": self.code, "message": self.message}},
        )


# --- Concrete errors used across the API ------------------------------------


class CredentialsError(AppError):
    """401 - bad login, bad/expired/mistyped token."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "invalid_credentials"


class ForbiddenError(AppError):
    """403 - authenticated but not allowed."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class NoAssignmentError(AppError):
    """403 - valid user with no route/vehicle assigned yet (decision #11)."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "no_assignment"


class NotFoundError(AppError):
    """404 - resource does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    """409 - duplicate/uniqueness violation."""

    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


# --- Handler registration ----------------------------------------------------


def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return exc.to_response()


def _validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"field": ".".join(str(loc) for loc in err["loc"][1:]), "message": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "details": details,
            }
        },
    )


def _http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Framework-raised HTTP errors (404 unknown route, 405 method, etc.) fit the envelope too
    code_map = {
        404: "not_found",
        405: "method_not_allowed",
    }
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code_map.get(exc.status_code, "http_error"),
                "message": str(exc.detail),
            }
        },
    )


def _unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    # Deliberate AppErrors are handled above; anything reaching here is a bug.
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": {"code": "internal_error", "message": "Unexpected server error"}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
