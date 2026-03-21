"""
upload_model.py — Package and upload a PyTorch model to S3 for SageMaker.

Run this ONCE before `terraform apply` to place model.tar.gz in the S3 bucket
that Terraform's SageMaker module references.

Usage:
    python scripts/upload_model.py --model-zip Model.zip --bucket <bucket_name>
    python scripts/upload_model.py --model-zip Model.zip --bucket <bucket_name> --region us-east-1

Steps:
  1. Unzip Model.zip → extract model.pth (and any other checkpoint files)
  2. Copy sagemaker/inference.py into the staging directory
  3. Create model.tar.gz containing model.pth + inference.py
  4. Upload model.tar.gz to s3://<bucket>/model/model.tar.gz
"""

import argparse
import logging
import os
import shutil
import sys
import tarfile
import tempfile
import zipfile

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# S3 key where SageMaker will look for the model artifact
S3_MODEL_KEY = "model/model.tar.gz"

# Paths to SageMaker serving files relative to the project root
SAGEMAKER_DIR = os.path.join(os.path.dirname(__file__), "..", "sagemaker")
INFERENCE_SCRIPT = os.path.join(SAGEMAKER_DIR, "inference.py")
REQUIREMENTS_FILE = os.path.join(SAGEMAKER_DIR, "requirements.txt")


def parse_args():
    parser = argparse.ArgumentParser(description="Package and upload model to S3")
    parser.add_argument("--model-zip", required=True, help="Path to Model.zip")
    parser.add_argument("--bucket", required=True, help="S3 bucket name for model artifacts")
    parser.add_argument("--region", default="us-east-1", help="AWS region (default: us-east-1)")
    parser.add_argument(
        "--s3-key",
        default=S3_MODEL_KEY,
        help=f"S3 key for the tarball (default: {S3_MODEL_KEY})",
    )
    return parser.parse_args()


def unzip_model(zip_path: str, staging_dir: str) -> None:
    """Extract Model.zip into staging_dir."""
    logger.info("Unzipping %s → %s", zip_path, staging_dir)
    if not os.path.exists(zip_path):
        logger.error("Model zip not found: %s", zip_path)
        sys.exit(1)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(staging_dir)

    contents = os.listdir(staging_dir)
    logger.info("Extracted files: %s", contents)

    # If everything landed in a subdirectory, flatten one level
    if len(contents) == 1 and os.path.isdir(os.path.join(staging_dir, contents[0])):
        sub = os.path.join(staging_dir, contents[0])
        for item in os.listdir(sub):
            shutil.move(os.path.join(sub, item), staging_dir)
        os.rmdir(sub)
        logger.info("Flattened subdirectory %s", contents[0])


def copy_inference_script(staging_dir: str) -> None:
    """Copy sagemaker/inference.py and requirements.txt into the staging directory."""
    for src_path, filename in [
        (INFERENCE_SCRIPT, "inference.py"),
        (REQUIREMENTS_FILE, "requirements.txt"),
    ]:
        src = os.path.abspath(src_path)
        dst = os.path.join(staging_dir, filename)
        if not os.path.exists(src):
            logger.warning("%s not found at %s — skipping", filename, src)
            continue
        shutil.copy2(src, dst)
        logger.info("Copied %s → %s", filename, dst)


def create_tarball(staging_dir: str, tarball_path: str) -> None:
    """Create model.tar.gz from all files in staging_dir."""
    logger.info("Creating tarball: %s", tarball_path)
    with tarfile.open(tarball_path, "w:gz") as tar:
        for filename in os.listdir(staging_dir):
            filepath = os.path.join(staging_dir, filename)
            tar.add(filepath, arcname=filename)
            logger.info("  + %s  (%s bytes)", filename, os.path.getsize(filepath))
    size_mb = os.path.getsize(tarball_path) / (1024 * 1024)
    logger.info("Tarball size: %.1f MB", size_mb)


def upload_to_s3(tarball_path: str, bucket: str, key: str, region: str) -> str:
    """Upload the tarball to S3 and return the s3:// URI."""
    s3 = boto3.client("s3", region_name=region)

    # Verify the bucket exists
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            logger.error(
                "Bucket '%s' does not exist. "
                "Run: terraform apply -target=module.sagemaker.aws_s3_bucket.model_artifacts",
                bucket,
            )
        else:
            logger.error("Cannot access bucket '%s': %s", bucket, e)
        sys.exit(1)

    logger.info("Uploading to s3://%s/%s ...", bucket, key)
    s3.upload_file(
        tarball_path,
        bucket,
        key,
        ExtraArgs={"ServerSideEncryption": "AES256"},
        Callback=_progress_callback(os.path.getsize(tarball_path)),
    )
    s3_uri = f"s3://{bucket}/{key}"
    logger.info("Upload complete: %s", s3_uri)
    return s3_uri


def _progress_callback(total_bytes):
    """Return a callback that logs upload progress."""
    uploaded = [0]

    def callback(bytes_transferred):
        uploaded[0] += bytes_transferred
        pct = uploaded[0] / total_bytes * 100
        if pct % 10 < (bytes_transferred / total_bytes * 100):
            logger.info("  Upload progress: %.0f%%", pct)

    return callback


def main():
    args = parse_args()

    with tempfile.TemporaryDirectory() as staging_dir:
        # 1. Unzip Model.zip
        unzip_model(args.model_zip, staging_dir)

        # 2. Copy inference.py (SageMaker serving script)
        copy_inference_script(staging_dir)

        # 3. Create model.tar.gz
        tarball_path = os.path.join(tempfile.gettempdir(), "model.tar.gz")
        create_tarball(staging_dir, tarball_path)

        # 4. Upload to S3
        s3_uri = upload_to_s3(tarball_path, args.bucket, args.s3_key, args.region)

    print(f"\n✅ Model uploaded successfully: {s3_uri}")
    print(f"\nNext step: run 'make tf-apply' to deploy the SageMaker endpoint.")


if __name__ == "__main__":
    main()
