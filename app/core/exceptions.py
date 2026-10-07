"""Custom exceptions mapped to HTTP error codes.

Each exception carries a human-readable `detail` and a machine-readable `code`.
The exception handler at the bottom converts them to consistent JSON responses.
"""

from fastapi import Request
from fastapi.responses import JSONResponse


class GeoAPIError(Exception):
    """Base exception for all domain errors in this API."""

    def __init__(self, detail: str, code: str) -> None:
        self.detail = detail
        self.code = code
        super().__init__(detail)


class UnsupportedFileTypeError(GeoAPIError):
    def __init__(self, detail: str = "Unsupported file type") -> None:
        super().__init__(detail=detail, code="UNSUPPORTED_FILE_TYPE")


class InvalidGeospatialFileError(GeoAPIError):
    def __init__(self, detail: str = "Invalid or corrupt geospatial file") -> None:
        super().__init__(detail=detail, code="INVALID_GEOSPATIAL_FILE")


class MissingCRSError(GeoAPIError):
    def __init__(self, detail: str = "Missing or unparseable CRS (.prj file)") -> None:
        super().__init__(detail=detail, code="MISSING_CRS")


class FileTooLargeError(GeoAPIError):
    def __init__(self, detail: str = "File exceeds maximum upload size") -> None:
        super().__init__(detail=detail, code="FILE_TOO_LARGE")


class GeoFileNotFoundError(GeoAPIError):
    """Named to avoid shadowing the builtin FileNotFoundError."""

    def __init__(self, detail: str = "File not found") -> None:
        super().__init__(detail=detail, code="FILE_NOT_FOUND")


class ZipSecurityError(GeoAPIError):
    def __init__(self, detail: str = "Zip file failed security validation") -> None:
        super().__init__(detail=detail, code="ZIP_SECURITY_ERROR")


# Maps each exception class to the HTTP status code it should produce.
_EXCEPTION_STATUS_MAP: dict[type[GeoAPIError], int] = {
    UnsupportedFileTypeError: 415,
    InvalidGeospatialFileError: 400,
    MissingCRSError: 422,
    FileTooLargeError: 413,
    GeoFileNotFoundError: 404,
    ZipSecurityError: 400,
}


async def geo_api_exception_handler(request: Request, exc: GeoAPIError) -> JSONResponse:
    """Convert any GeoAPIError into a structured JSON error response."""
    status_code = _EXCEPTION_STATUS_MAP.get(type(exc), 500)
    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.detail, "code": exc.code},
    )
