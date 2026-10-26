from pathlib import Path
from typing import Protocol

from app.config import settings


class Storage(Protocol):
    def put(self, key: str, data: bytes): ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str): ...


class LocalStorage:
    def path(self, key):
        root = Path(settings().storage_path).resolve()
        target = (root / key).resolve()
        if root not in target.parents:
            raise ValueError("Invalid storage path")
        return target

    def put(self, key, data):
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def get(self, key):
        return self.path(key).read_bytes()

    def delete(self, key):
        self.path(key).unlink(missing_ok=True)


class S3Storage:
    def __init__(self):
        import boto3

        self.client = boto3.client("s3", endpoint_url=settings().s3_endpoint_url or None)
        self.bucket = settings().s3_bucket
        if not self.bucket:
            raise RuntimeError("S3_BUCKET is required")

    def put(self, key, data):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ServerSideEncryption="AES256")

    def get(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)


def storage() -> Storage:
    return S3Storage() if settings().storage_backend == "s3" else LocalStorage()
