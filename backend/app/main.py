from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.errors import validation_error_response

app = FastAPI(
    title="Personal Air Exposure Companion API",
    version="0.1.0",
    description="MVP contract for transparent, duration-weighted PM2.5 exposure estimates.",
)

MAX_REQUEST_BYTES = 32 * 1024


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    """Reject unexpectedly large request bodies before model validation."""
    content_length = request.headers.get("content-length")
    if content_length is not None and content_length.isdigit() and int(content_length) > MAX_REQUEST_BYTES:
        return JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "REQUEST_TOO_LARGE",
                    "message": f"Request body must not exceed {MAX_REQUEST_BYTES} bytes.",
                }
            },
        )

    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        return JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "REQUEST_TOO_LARGE",
                    "message": f"Request body must not exceed {MAX_REQUEST_BYTES} bytes.",
                }
            },
        )
    return await call_next(request)

app.add_exception_handler(RequestValidationError, validation_error_response)
app.include_router(router)
