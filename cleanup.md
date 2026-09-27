# Assignment cleanup

Run these commands only after saving the required evidence.
They delete the assignment resources.

Use the original working folder and its local settings file.
Do not commit that settings file.

```bash
cd ~/AWS-Assignments/file-notification-pipeline
source assignment-env.sh
```

Check that all variables refer to the intended assignment resources.
Stop if any required variable is empty.

## 1. Delete the SQS event source mapping

```bash
aws lambda delete-event-source-mapping \
  --uuid "$MAPPING_UUID" \
  --profile root-bootstrap
```

Deletion is asynchronous. Check its status:

```bash
aws lambda get-event-source-mapping \
  --uuid "$MAPPING_UUID" \
  --profile root-bootstrap \
  --query State --output text
```

Wait and repeat the check until ResourceNotFoundException confirms deletion.
Other errors do not confirm deletion.

## 2. Delete the Lambda function

```bash
aws lambda delete-function --function-name "$FUNCTION_NAME"
```

## 3. Delete the SNS topic and SQS queue

Deleting the SNS topic also removes its subscriptions.

```bash
aws sns delete-topic --topic-arn "$TOPIC_ARN"
aws sqs delete-queue --queue-url "$QUEUE_URL"
```

## 4. Delete the sample object and bucket

```bash
aws s3api delete-object --bucket "$BUCKET_NAME" --key "$FILE_KEY"
aws s3api delete-bucket --bucket "$BUCKET_NAME"
```

If bucket deletion reports BucketNotEmpty, inspect the remaining contents.
Do not delete unrelated objects.

## 5. Delete the application log group

```bash
aws logs delete-log-group \
  --log-group-name "$LOG_GROUP" \
  --profile root-bootstrap
```

## 6. Delete the Lambda role

```bash
aws iam delete-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name FileNotificationPermissions \
  --profile root-bootstrap

aws iam delete-role \
  --role-name "$ROLE_NAME" \
  --profile root-bootstrap
```

## 7. Remove the assignment-only IAM user

Only use this section if the user remains dedicated to this assignment.

```bash
for POLICY_NAME in AssignmentS3Access AssignmentSQSAccess AssignmentSNSAccess AssignmentLambdaAccess
do
  aws iam delete-user-policy \
    --user-name talha-cli-assignment \
    --policy-name "$POLICY_NAME" \
    --profile root-bootstrap || break
done

aws iam detach-user-policy \
  --user-name talha-cli-assignment \
  --policy-arn arn:aws:iam::aws:policy/SignInLocalDevelopmentAccess \
  --profile root-bootstrap

aws iam delete-login-profile \
  --user-name talha-cli-assignment \
  --profile root-bootstrap

aws iam delete-user \
  --user-name talha-cli-assignment \
  --profile root-bootstrap
```

Stop and investigate any error. Additional credentials or attachments,
if added outside this assignment, may prevent user deletion.

## 8. End local CLI sessions

```bash
aws logout --profile talha-assignment
aws logout --profile root-bootstrap
```

Keep the sanitized repository and screenshots as evidence.
