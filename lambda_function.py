import json
import os
import time

import boto3
from botocore.config import Config

config = Config(
    connect_timeout=3,
    read_timeout=5,
    retries={"mode": "standard", "total_max_attempts": 2},
)

s3 = boto3.client("s3", config=config)
sns = boto3.client("sns", config=config)
logs = boto3.client("logs", config=config)


def write_log(level, message, **details):
    entry = {
        "level": level,
        "message": message,
        **details,
    }

    logs.put_log_events(
        logGroupName=os.environ["LOG_GROUP"],
        logStreamName=os.environ["LOG_STREAM"],
        logEvents=[
            {
                "timestamp": int(time.time() * 1000),
                "message": json.dumps(entry, default=str),
            }
        ],
    )


def lambda_handler(event, context):
    failures = []

    for record in event.get("Records", []):
        message_id = record["messageId"]

        try:
            payload = json.loads(record["body"])

            if not isinstance(payload, dict):
                raise ValueError("Message body must be a JSON object.")

            bucket = payload.get("bucket")
            key = payload.get("key")

            if not isinstance(bucket, str) or not bucket:
                raise ValueError("A non-empty bucket name is required.")

            if not isinstance(key, str) or not key:
                raise ValueError("A non-empty file key is required.")

            if (
                bucket != os.environ["ALLOWED_BUCKET"]
                or key != os.environ["ALLOWED_KEY"]
            ):
                raise ValueError("Bucket or key is outside assignment scope.")

            write_log(
                "INFO",
                "Processing started",
                message_id=message_id,
                request_id=context.aws_request_id,
                bucket=bucket,
                key=key,
            )

            metadata = s3.head_object(Bucket=bucket, Key=key)

            details = {
                "file_name": key.rsplit("/", 1)[-1],
                "key": key,
                "bucket": bucket,
                "size_bytes": metadata["ContentLength"],
                "content_type": metadata.get(
                    "ContentType", "application/octet-stream"
                ),
                "last_modified": metadata["LastModified"].isoformat(),
                "etag": metadata["ETag"].strip('"'),
                "storage_class": metadata.get("StorageClass", "STANDARD"),
            }

            email_body = "\n".join([
                "S3 File Notification",
                "",
                f"File name: {details['file_name']}",
                f"Object key: {details['key']}",
                f"Bucket: {details['bucket']}",
                f"Size: {details['size_bytes']} bytes",
                f"Content type: {details['content_type']}",
                f"Last modified: {details['last_modified']}",
                f"ETag: {details['etag']}",
                f"Storage class: {details['storage_class']}",
                "",
                f"SQS message ID: {message_id}",
            ])

            result = sns.publish(
                TopicArn=os.environ["TOPIC_ARN"],
                Subject="AWS Assignment - S3 File Details",
                Message=email_body,
            )

            write_log(
                "INFO",
                "File notification published",
                message_id=message_id,
                sns_message_id=result["MessageId"],
                **details,
            )

        except Exception as error:
            failures.append({"itemIdentifier": message_id})

            try:
                write_log(
                    "ERROR",
                    "Message processing failed",
                    message_id=message_id,
                    error_type=type(error).__name__,
                    error=str(error),
                )
            except Exception:
                # Propagate logging failure so the invocation also fails.
                raise

    return {"batchItemFailures": failures}
