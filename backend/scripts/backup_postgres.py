"""Create a custom-format PostgreSQL dump and verify its offsite upload."""
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import tempfile

import boto3


def main() -> None:
    environment = os.environ.copy()
    environment["PGPASSWORD"] = Path(environment["DB_PASSWORD_FILE"]).read_text().strip()
    environment["AWS_ACCESS_KEY_ID"] = Path(environment["AWS_ACCESS_KEY_ID_FILE"]).read_text().strip()
    environment["AWS_SECRET_ACCESS_KEY"] = Path(environment["AWS_SECRET_ACCESS_KEY_FILE"]).read_text().strip()
    bucket = environment["BACKUP_BUCKET"]
    options = {"region_name": environment.get("S3_REGION", "us-east-1")}
    if environment.get("S3_ENDPOINT_URL"):
        options["endpoint_url"] = environment["S3_ENDPOINT_URL"]
    client = boto3.client("s3", aws_access_key_id=environment["AWS_ACCESS_KEY_ID"],
                          aws_secret_access_key=environment["AWS_SECRET_ACCESS_KEY"], **options)
    with tempfile.TemporaryDirectory() as directory:
        dump = Path(directory) / "database.dump"
        subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--file", str(dump)],
                       env=environment, check=True)
        if dump.stat().st_size == 0:
            raise RuntimeError("Database dump is empty")
        key = f"postgres/{datetime.now(timezone.utc):%Y/%m/%d/%Y%m%dT%H%M%SZ}.dump"
        client.upload_file(str(dump), bucket, key, ExtraArgs={"ServerSideEncryption": "AES256"})
        metadata = client.head_object(Bucket=bucket, Key=key)
        if metadata["ContentLength"] != dump.stat().st_size:
            raise RuntimeError("Uploaded backup size does not match local dump")
        print(f"Verified backup s3://{bucket}/{key} ({dump.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
