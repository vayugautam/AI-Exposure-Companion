from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def validation_error_response(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    del request
    details: list[dict[str, Any]] = []
    for error in exc.errors():
        details.append(
            {
                "location": list(error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
        )

    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "details": details,
            }
        },
    )
