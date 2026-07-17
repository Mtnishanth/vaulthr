import json
import uuid
import boto3
import os
from datetime import datetime, timezone
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all
patch_all()
from utils import decode_jwt_claims, get_user_info, write_audit_log, api_response

# AWS clients — created once outside handler for reuse across warm invocations
s3       = boto3.client('s3', region_name='ap-south-2')
dynamodb = boto3.resource('dynamodb', region_name='ap-south-2')

# ── Constants (must match the project contract exactly) ──────────────────────
import os
BUCKET_NAME    = os.environ['BUCKET_NAME']
METADATA_TABLE = os.environ['METADATA_TABLE']

ALLOWED_TYPES = {
    'offer_letter',
    'contract',
    'payslip',
    'appraisal',
    'compliance_certificate'
}

# ── Main handler ─────────────────────────────────────────────────────────────
def lambda_handler(event, context):

    # ── STEP 1: Decode JWT claims injected by API Gateway Cognito Authorizer
    claims = decode_jwt_claims(event)
    user   = get_user_info(claims)

    # Reject if token is missing or malformed
    if not user['employee_id'] or not user['role']:
        return api_response(401, {'error': 'Unauthorized — missing identity in token'})

    # ── STEP 2: Parse the request body sent by the frontend
    try:
        body = json.loads(event.get('body') or '{}')
    except json.JSONDecodeError:
        return api_response(400, {'error': 'Invalid JSON in request body'})

    employee_id   = body.get('employee_id', '').strip()
    document_type = body.get('document_type', '').strip()
    filename      = body.get('filename', '').strip()
    tags          = body.get('tags', [])

    # ── STEP 3: Validate all required fields are present
    if not employee_id:
        return api_response(400, {'error': 'Missing field: employee_id'})
    if not document_type:
        return api_response(400, {'error': 'Missing field: document_type'})
    if not filename:
        return api_response(400, {'error': 'Missing field: filename'})

    # ── STEP 4: Validate document_type is one of the 5 allowed values
    if document_type not in ALLOWED_TYPES:
        return api_response(400, {
            'error': f"Invalid document_type '{document_type}'.",
            'allowed_values': sorted(ALLOWED_TYPES)
        })

    # ── STEP 5: Role-based permission check
    #    Employee  → can only upload to their OWN employee_id
    #    Manager   → can upload on behalf of direct reports (HR use case)
    #    HR_Admin  → can upload for anyone
    role = user['role']

    if role == 'Employee' and user['employee_id'] != employee_id:
        return api_response(403, {
            'error': 'Access denied — employees can only upload their own documents'
        })

    if role not in ('Employee', 'Manager', 'HR_Admin'):
        return api_response(403, {'error': f"Unknown role '{role}'"})

    # ── STEP 6: Generate unique document_id (UUID v4 per contract)
    document_id = str(uuid.uuid4())

    # ── STEP 7: Build S3 key — must follow contract exactly:
    #    documents/{employee_id}/{document_type}/{filename}
    s3_key = f"documents/{employee_id}/{document_type}/{filename}"

    # ── STEP 8: Write metadata to DynamoDB BEFORE generating the URL
    #    This ensures a record always exists even if the upload is abandoned
    timestamp = (
        datetime.now(timezone.utc)
        .isoformat(timespec='seconds')
        .replace('+00:00', 'Z')
    )

    table = dynamodb.Table(METADATA_TABLE)
    table.put_item(Item={
        'document_id':      document_id,
        'employee_id':      employee_id,
        'uploaded_by':      user['employee_id'],   # who triggered the upload
        'document_type':    document_type,
        's3_key':           s3_key,
        'upload_timestamp': timestamp,
        'tags':             tags,
        'is_deleted':       False
    })

    # ── STEP 9: Generate pre-signed PUT URL (valid 15 minutes = 900 seconds)
    #    The frontend uses this URL to PUT the file directly into S3
    #    No file bytes ever pass through Lambda
    presigned_url = s3.generate_presigned_url(
        'put_object',
        Params={
            'Bucket': BUCKET_NAME,
            'Key':    s3_key
        },
        ExpiresIn=900
    )

    # ── STEP 10: Write audit log (UPLOAD action)
    write_audit_log(user['employee_id'], 'UPLOAD', document_id)

    # ── STEP 11: Return document_id + upload URL to the frontend
    return api_response(200, {
        'document_id': document_id,
        'upload_url':  presigned_url
    })