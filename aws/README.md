# Connect Jarvis to your AWS account

The setup below creates a dedicated **raw-recording** bucket. Transcripts and summaries remain local and indefinite; this milestone does not back up the SQLite database.

**Current installation:** the stack is now deployed in Sydney, seven recordings have been uploaded and retrieved with verified checksums, and the background archive worker uses the `jarvis-archive` profile. Its dedicated service identity has the bucket-only policy as a permissions boundary as well as an attached policy. Access keys are stored in the local AWS credentials file; there is no console password for this identity. The temporary root setup session has been signed out. The instructions below describe setup on another installation; no repeat setup is needed here.

## Create the bucket and cleanup resources

1. Sign into the AWS console and open **CloudFormation** in your chosen region (Tokyo `ap-northeast-1` is a reasonable nearby option).
2. Choose **Create stack → With new resources → Upload a template file** and select `aws/archive-stack.yaml` from this project.
3. Name the stack `jarvis-audio-archive`. The template creates a private S3 bucket, an hourly cleanup Lambda and its execution role, a schedule, and a restricted managed policy for the PC. Acknowledge IAM resource creation and create the stack.
4. When the stack is complete, copy **BucketName** and **Region** from **Outputs**. Do not send access keys or passwords in chat.

The template creates no AWS user or access key, enables all public-access blocks, disables ACLs, requires HTTPS, and encrypts objects with S3-managed AES256. It deliberately leaves versioning off: enabling versioning later would preserve old raw recordings. The client refuses enabled or suspended versioning.

## Authenticate this PC

Use the official AWS CLI v2 and an AWS profile with access to this bucket, preferably temporary credentials through IAM Identity Center where your account supports it:

```powershell
aws configure sso --profile jarvis
aws sso login --profile jarvis
```

The stack's `ClientPolicyArn` identifies the restricted policy to attach to the role/profile you will use. This step depends on how your AWS account manages access; account sign-in by itself does not configure the PC SDK. Never use root access keys. Temporary credentials must be renewed when they expire; failed uploads remain queued locally within the 30-day recording-retention window.

Copy `aws/config.example.json` to `jarvis-data/aws.json` and replace the bucket and region. The profile is `jarvis` by default in the example; omit it only when using another standard credential-chain method. Do not put secrets in this JSON file.

```powershell
.venv\Scripts\python.exe -m pip install --use-feature=truststore -r receiver/requirements-aws.txt
.venv\Scripts\python.exe receiver/s3_archive.py --check
.venv\Scripts\python.exe receiver/s3_archive.py --once
```

`--check` performs read-only bucket validation; `--once` uploads eligible recordings. Then run `start-cloud-archive.ps1` for continuous synchronization. The phone has no AWS credentials: uploads go through the PC.

## Retention, recovery, and costs

- Upload only completed transcripts' raw files, with a verified SHA-256 checksum and deterministic key. A lost upload acknowledgement is recovered without uploading another copy. Upload errors remain visible in SQLite `cloud_uploads` and retry next cycle.
- Local raw copies still expire at 30 days. This release does not evict local audio early. If a local file is missing, authenticated playback can retrieve its verified cloud copy before its retention deadline.
- The PC removes known expired cloud objects by **capture time**. The hourly AWS function independently scans the dedicated prefix and removes recognized recording keys older than 30 days, even while the PC is offline. Normal cleanup granularity is up to an hour plus AWS execution delays; this is not guaranteed deletion at the exact second.
- S3's 30-day **upload-age** lifecycle rule is an additional backstop. Lifecycle processing is asynchronous. Keep the scheduled function enabled: delayed uploads cannot rely on upload-age expiration to enforce capture-age retention.
- No versioning, replication, or AWS Backup is configured. Adding any later requires revisiting raw-data deletion. Deleting the CloudFormation stack retains the bucket but removes its hourly cleanup, so do not delete the stack while continuing uploads.
- Raw PCM currently uses about 83 GB for one continuously recorded 30-day stream, plus request/retrieval charges. This is more than the earlier compressed-audio estimate: compression is not yet implemented. S3, Lambda and schedule costs depend on region and usage. AWS budgets are alerts, not a hard spending cap; monitor billing against the overall $30/month target.
- Cloud copies of permanent transcripts/summaries and disaster recovery for the database are separate future work.

References: [S3 expiration behavior](https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-expire-general-considerations.html), [AWS CLI installation](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html), [IAM Identity Center profiles](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html).
