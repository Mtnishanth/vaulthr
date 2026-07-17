# VaultHR — Employee Document Vault

![CI/CD Pipeline](https://github.com/Mtnishanth/vaulthr/actions/workflows/deploy.yml/badge.svg)

## Overview
Secure HR document management system built on AWS.

## Architecture
- Frontend: React/HTML hosted on S3 + CloudFront
- Auth: Amazon Cognito
- API: API Gateway + Lambda (Python 3.12)
- Storage: S3 + DynamoDB
- Observability: CloudWatch + X-Ray

## Lambda Functions
| Function | Route | Purpose |
|---|---|---|
| UploadFunction | POST /upload | Generate presigned PUT URL |
| ListFilesFunction | GET /files | List documents by role |
| DownloadFunction | GET /download/{id} | Generate presigned GET URL |
| DeleteFunction | DELETE /files/{id} | Soft delete document |
