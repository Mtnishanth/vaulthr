import json
import boto3
import os
from boto3.dynamodb.conditions import Attr
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all
patch_all()
from utils import decode_jwt_claims, get_user_info, write_audit_log, api_response

# AWS clients
s3       = boto3.client('s3', region_name='ap-south-2')
dynamodb = boto3.resource('dynamodb', region_name='ap-south-2')

# ── Constants ────────────────────────────────────────────────────────────────
import os
BUCKET_NAME    = os.environ['BUCKET_NAME']     # employee-document-vault
METADATA_TABLE = os.environ['METADATA_TABLE']  # document_metadata
MANAGER_TABLE  = os.environ['MANAGER_TABLE']   # manager_mapping


# ── Access checker ───────────────────────────────────────────────────────────
def can_access(user, owner_employee_id):
    """
    Returns True if the caller is allowed to access
    a document belonging to owner_employee_id.

    Rules (from contract section 15):
      Employee  → only their own employee_id
      Manager   → only employees in manager_mapping
      HR_Admin  → everything
    """
    role        = user['role']
    employee_id = user['employee_id']

    # HR_Admin: unrestricted
    if role == 'HR_Admin':
        return True

    # Employee: own documents only
    if role == 'Employee':
        return employee_id == owner_employee_id

    # Manager: own docs + mapped direct reports
    if role == 'Manager':
        # Manager accessing their own document
        if employee_id == owner_employee_id:
            return True

        # Check manager_mapping table for the relationship
        manager_table = dynamodb.Table(MANAGER_TABLE)
        response      = manager_table.get_item(Key={
            'manager_id':  employee_id,
            'employee_id': owner_employee_id
        })
        # If item exists → relationship confirmed → access granted
        return 'Item' in response

    # Unknown role → deny
    return False


# ── Main handler ─────────────────────────────────────────────────────────────
def lambda_handler(event, context):

    # ── STEP 1: Decode JWT
    claims = decode_jwt_claims(event)
    user   = get_user_info(claims)

    if not user['employee_id']:
        return api_response(401, {'error': 'Unauthorized'})

    # ── STEP 2: Get doc_id from URL path
    #    API route is:  GET /download/{doc_id}
    #    API Gateway puts path params here:
    path_params = event.get('pathParameters') or {}
    doc_id      = path_params.get('doc_id', '').strip()

    if not doc_id:
        return api_response(400, {'error': 'Missing doc_id in path'})

    # ── STEP 3: Fetch document metadata from DynamoDB
    table    = dynamodb.Table(METADATA_TABLE)
    response = table.get_item(Key={'document_id': doc_id})
    item     = response.get('Item')

    # Document doesn't exist at all
    if not item:
        return api_response(404, {'error': 'Document not found'})

    # Document was soft-deleted — treat as not found
    if item.get('is_deleted', False):
        return api_response(404, {'error': 'Document not found'})

    # ── STEP 4: Authorization check
    #    Does this caller have the right to access this document?
    owner_employee_id = item['employee_id']

    if not can_access(user, owner_employee_id):
        # Still write audit log for denied attempts — important for security
        write_audit_log(user['employee_id'], 'DOWNLOAD', doc_id)
        return api_response(403, {
            'error': 'Access denied — you do not have permission to download this document'
        })

    # ── STEP 5: Generate pre-signed GET URL
    #    Valid for exactly 15 minutes (900 seconds) per contract section 18
    #    The frontend opens this URL directly — no file bytes go through Lambda
    presigned_url = s3.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': BUCKET_NAME,
            'Key':    item['s3_key']
        },
        ExpiresIn=900   # 15 minutes
    )

    # ── STEP 6: Write audit log (successful download)
    write_audit_log(user['employee_id'], 'DOWNLOAD', doc_id)

    # ── STEP 7: Return the presigned URL to frontend
    #    Frontend opens this URL in a new tab or triggers a download
    return api_response(200, {
        'download_url': presigned_url,
        'filename':     item['s3_key'].split('/')[-1],   # just the filename
        'document_type': item.get('document_type'),
        'employee_id':   item.get('employee_id')
    })