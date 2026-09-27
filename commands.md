# CLI command reference

These commands document the implemented assignment.
They are a reference, not a one-click deployment script.

Run commands in order and stop on errors. Use your own AWS account,
resource names and email. Never commit generated environment files.

## 1. Authentication and variables

AWS CLI v2 with `aws login` support is required.

The existing IAM user needs deployment permissions. The administrator
profile is used for permission provisioning, execution-role creation,
CloudWatch setup, and event source mapping creation.

```bash
aws configure set region eu-north-1 --profile talha-assignment
aws login --profile talha-assignment

export AWS_PROFILE=talha-assignment
export AWS_DEFAULT_REGION=eu-north-1
export AWS_PAGER=""

export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export BUCKET_NAME="your-globally-unique-bucket-name"
export FILE_KEY="sample.txt"
export QUEUE_NAME="talha-file-notify-queue"
export QUEUE_ARN="arn:aws:sqs:eu-north-1:${ACCOUNT_ID}:${QUEUE_NAME}"
export TOPIC_NAME="talha-file-notify-topic"
export TOPIC_ARN="arn:aws:sns:eu-north-1:${ACCOUNT_ID}:${TOPIC_NAME}"
export FUNCTION_NAME="talha-file-notifier"
export ROLE_NAME="talha-file-notifier-role"
export ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
export LOG_GROUP="/assignment/talha-file-notifier"
export LOG_STREAM="processing"
export LOG_STREAM_ARN="arn:aws:logs:eu-north-1:${ACCOUNT_ID}:log-group:${LOG_GROUP}:log-stream:${LOG_STREAM}"
```

## 2. Prepare and attach deployment policies

Copy the policy templates to a local directory named `private-policies`.
Replace all angle-bracket placeholders with the appropriate values above.
Keep these generated policies out of Git.

For each service policy, attach its rendered copy using an authorized
administrator profile. In this assignment that profile was root-bootstrap.

Example:

```bash
aws iam put-user-policy \
  --user-name talha-cli-assignment \
  --policy-name AssignmentS3Access \
  --policy-document file://private-policies/iam-user-s3-policy.json \
  --profile root-bootstrap
```

Repeat with these mappings:

| Template | Inline policy name |
|---|---|
| iam-user-sqs-policy.json | AssignmentSQSAccess |
| iam-user-sns-policy.json | AssignmentSNSAccess |
| iam-user-lambda-policy.json | AssignmentLambdaAccess |

IAM browser-based CLI login also requires SignInLocalDevelopmentAccess.
The IAM user's sign-in password was created separately using
`aws iam create-login-profile`; credentials are intentionally omitted here.

## 3. S3 bucket and sample file

```bash
aws s3api create-bucket \
  --bucket "$BUCKET_NAME" \
  --region eu-north-1 \
  --create-bucket-configuration LocationConstraint=eu-north-1

printf 'Hello from Talha!\nThis file tests the AWS notification pipeline.\n' > sample.txt

aws s3api put-object \
  --bucket "$BUCKET_NAME" \
  --key "$FILE_KEY" \
  --body sample.txt \
  --content-type text/plain

aws s3api head-object --bucket "$BUCKET_NAME" --key "$FILE_KEY"
```

## 4. SQS queue

```bash
QUEUE_URL=$(aws sqs create-queue \
  --queue-name "$QUEUE_NAME" \
  --attributes VisibilityTimeout=180,ReceiveMessageWaitTimeSeconds=10,SqsManagedSseEnabled=true \
  --query QueueUrl --output text)
```

## 5. SNS topic and email subscription

```bash
aws sns create-topic --name "$TOPIC_NAME"

read -r -p "Notification email: " NOTIFY_EMAIL

aws sns subscribe \
  --topic-arn "$TOPIC_ARN" \
  --protocol email \
  --notification-endpoint "$NOTIFY_EMAIL"
```

Open the received confirmation email and click Confirm subscription.

```bash
aws sns list-subscriptions-by-topic \
  --topic-arn "$TOPIC_ARN" \
  --query "Subscriptions[?Protocol=='email'].{Protocol:Protocol,Pending:SubscriptionArn=='PendingConfirmation'}" \
  --output table
```

Confirm that the email subscription exists and Pending is False.

## 6. CloudWatch and Lambda execution role

```bash
aws logs create-log-group \
  --log-group-name "$LOG_GROUP" --profile root-bootstrap

aws logs create-log-stream \
  --log-group-name "$LOG_GROUP" \
  --log-stream-name "$LOG_STREAM" --profile root-bootstrap

aws logs put-retention-policy \
  --log-group-name "$LOG_GROUP" \
  --retention-in-days 7 --profile root-bootstrap

aws iam create-role \
  --role-name "$ROLE_NAME" \
  --assume-role-policy-document file://policies/lambda-trust-policy.json \
  --profile root-bootstrap

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name FileNotificationPermissions \
  --policy-document file://private-policies/lambda-permissions-policy.json \
  --profile root-bootstrap
```

## 7. Package and deploy Lambda

```bash
python3 -m py_compile lambda_function.py
python3 -m zipfile -c function.zip lambda_function.py

aws lambda create-function \
  --function-name "$FUNCTION_NAME" \
  --runtime python3.13 \
  --role "$ROLE_ARN" \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://function.zip \
  --timeout 30 \
  --memory-size 128 \
  --environment "Variables={TOPIC_ARN=$TOPIC_ARN,LOG_GROUP=$LOG_GROUP,LOG_STREAM=$LOG_STREAM,ALLOWED_BUCKET=$BUCKET_NAME,ALLOWED_KEY=$FILE_KEY}"

aws lambda wait function-active-v2 --function-name "$FUNCTION_NAME"
```

Allow time for IAM role propagation if Lambda initially cannot assume it.

## 8. Send and inspect the SQS message

Perform this inspection before enabling the Lambda trigger.

```bash
aws sqs send-message \
  --queue-url "$QUEUE_URL" \
  --message-body "{\"bucket\":\"$BUCKET_NAME\",\"key\":\"$FILE_KEY\"}"

aws sqs receive-message \
  --queue-url "$QUEUE_URL" \
  --max-number-of-messages 1 \
  --wait-time-seconds 20 \
  --visibility-timeout 0 \
  --query 'Messages[].{MessageId:MessageId,Body:Body}'
```

Receiving does not delete the message. A receive may return no message;
retry the receive request before sending another message.

## 9. Connect SQS to Lambda

```bash
MAPPING_UUID=$(aws lambda create-event-source-mapping \
  --function-name "$FUNCTION_NAME" \
  --event-source-arn "$QUEUE_ARN" \
  --batch-size 1 \
  --maximum-batching-window-in-seconds 0 \
  --function-response-types ReportBatchItemFailures \
  --enabled \
  --profile root-bootstrap \
  --query UUID --output text)

aws lambda get-event-source-mapping \
  --uuid "$MAPPING_UUID" \
  --profile root-bootstrap \
  --query '{State:State,LastResult:LastProcessingResult}'
```

Wait until the mapping is Enabled. The pending message can then be processed.

## 10. Verify processing

```bash
aws logs get-log-events \
  --log-group-name "$LOG_GROUP" \
  --log-stream-name "$LOG_STREAM" \
  --start-from-head \
  --query 'events[].message' --output text

aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
```

Verify the final email and the "File notification published" application log.
Empty queue counts alone do not prove successful delivery.

See cleanup.md to remove the assignment resources.
