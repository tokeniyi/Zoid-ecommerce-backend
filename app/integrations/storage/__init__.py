"""Concrete file stores, plus the selection driven by configuration."""

from app.integrations.storage.cloudinary import CloudinaryFileStorage
from app.integrations.storage.contract import (
    AbstractFileStorage,
    FileUpload,
    StoredFile,
)
from app.integrations.storage.factory import (
    build_file_storage,
    supported_providers,
)
from app.integrations.storage.s3 import S3FileStorage

__all__ = [
    "AbstractFileStorage",
    "CloudinaryFileStorage",
    "FileUpload",
    "S3FileStorage",
    "StoredFile",
    "build_file_storage",
    "supported_providers",
]
