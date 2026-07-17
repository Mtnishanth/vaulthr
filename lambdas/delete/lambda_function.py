import json
import boto3
import os
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all
patch_all()
from utils import decode_jwt_claims, get_user_info, write_audit_log, api_response

# AWS client
dynamodb = boto3.resource('dynamodb', region_name='ap-south-2')

# ── Constants ────────────────────────────────────────────────────────────────
import os
METADATA_TABLE = os.environ['METADATA_TABLE']  # document_metadata


# ── Main handler ─────────────────────────────────────────────────────────────
def lambda_handler(event, context):

    # ── STEP 1: Decode JWT
    claims = decode_jwt_claims(event)
    user   = get_user_info(claims)

    if not user['employee_id']:
        return api_response(401, {'error': 'Unauthorized'})

    role        = user['role']
    employee_id = user['employee_id']

    # ── STEP 2: Get doc_id from URL path
    #    API route is:  DELETE /files/{doc_id}
    path_params = event.get('pathParameters') or {}
    doc_id      = path_params.get('doc_id', '').strip()

    if not doc_id:
        return api_response(400, {'error': 'Missing doc_id in path'})

    # ── STEP 3: Fetch the document from DynamoDB
    #    We need to know WHO owns it before deciding if deletion is allowed
   # ── STEP 3: Role check FIRST — before hitting DynamoDB
    if role == 'Manager':
        return api_response(403, {
            'error': 'Access denied — managers cannot delete documents'
        })

    # ── STEP 4: Fetch the document from DynamoDB
    table    = dynamodb.Table(METADATA_TABLE)
    response = table.get_item(Key={'document_id': doc_id})
    item     = response.get('Item')

    if not item:
        return api_response(404, {'error': 'Document not found'})

    if item.get('is_deleted', False):
        return api_response(400, {'error': 'Document is already deleted'})

    # ── STEP 4: Role-based permission check
    #
    #    Per contract section 19:
    #      HR_Admin  → can delete any document
    #      Employee  → can only delete their own documents
    #      Manager   → NOT allowed to delete (contract rule)

    if role == 'Manager':
        return api_response(403, {
            'error': 'Access denied — managers cannot delete documents'
        })

    if role == 'Employee' and item['employee_id'] != employee_id:
        return api_response(403, {
            'error': 'Access denied — you can only delete your own documents'
        })

    # HR_Admin passes through — no restriction

    # ── STEP 5: Soft delete — update is_deleted flag ONLY
    #
    #    CRITICAL: This must NEVER delete the S3 object or DynamoDB item.
    #    Contract section 19 explicitly states:
    #      Must NOT: Delete S3 object
    #      Must NOT: Delete DynamoDB item
    #
    #    We ONLY flip is_deleted = True
    table.update_item(
        Key={'document_id': doc_id},
        UpdateExpression='SET is_deleted = :val',
        ExpressionAttributeValues={':val': True}
    )

    # ── STEP 6: Write audit log
    write_audit_log(employee_id, 'DELETE', doc_id)

    # ── STEP 7: Return success
    return api_response(200, {
        'message':     'Document deleted successfully',
        'document_id': doc_id,
        'note':        'File preserved in S3. Metadata flagged as deleted in DynamoDB.'
    })
