import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

logger = logging.getLogger("app")

GENERIC_ERROR = {"detail": "Internal server error"}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(IntegrityError)
    def integrity_error_handler(request: Request, exc: IntegrityError):
        # Unique/FK/check violations surface as a consistent conflict response
        # without leaking constraint names, SQL, or database details.
        logger.warning("Integrity error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "The request conflicts with existing records"},
        )

    @app.exception_handler(SQLAlchemyError)
    def database_error_handler(request: Request, exc: SQLAlchemyError):
        logger.exception("Database error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=GENERIC_ERROR)

    @app.exception_handler(Exception)
    def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=GENERIC_ERROR)
