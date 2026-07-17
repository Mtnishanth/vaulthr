import json
import boto3
import os
from boto3.dynamodb.conditions import Key, Attr
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all
patch_all()
from utils import decode_jwt_claims, get_user_info, write_audit_log, api_response

dynamodb = boto3.resource('dynamodb', region_name='ap-south-2')

import os
METADATA_TABLE = os.environ['METADATA_TABLE']   # document_metadata
MANAGER_TABLE  = os.environ['MANAGER_TABLE']    # manager_mapping


def decimal_clean(obj):
    """DynamoDB returns Decimal — JSON can't serialize it. Convert here."""
    if isinstance(obj, list):    return [decimal_clean(i) for i in obj]
    if isinstance(obj, dict):    return {k: decimal_clean(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return int(obj) if obj % 1 == 0 else float(obj)
    return obj


def lambda_handler(event, context):

    # ── STEP 1: Decode JWT ───────────────────────────────────────────────────
    claims = decode_jwt_claims(event)
    user   = get_user_info(claims)

    if not user['employee_id']:
        return api_response(401, {'error': 'Unauthorized'})

    role        = user['role']
    employee_id = user['employee_id']

    metadata_table = dynamodb.Table(METADATA_TABLE)

    # ── STEP 2: Fetch documents based on role ────────────────────────────────

    if role == 'HR_Admin':
        response = metadata_table.scan(
            FilterExpression=Attr('is_deleted').eq(False)
        )
        items = response.get('Items', [])

    elif role == 'Manager':
        manager_table    = dynamodb.Table(MANAGER_TABLE)
        mapping_response = manager_table.scan(
            FilterExpression=Attr('manager_id').eq(employee_id)
        )
        direct_report_ids = [
            m['employee_id'] for m in mapping_response.get('Items', [])
        ]
        accessible_ids = set(direct_report_ids + [employee_id])

        items = []
        for emp_id in accessible_ids:
            resp = metadata_table.scan(
                FilterExpression=Attr('employee_id').eq(emp_id) &
                                 Attr('is_deleted').eq(False)
            )
            items.extend(resp.get('Items', []))

    else:
        response = metadata_table.scan(
            FilterExpression=Attr('employee_id').eq(employee_id) &
                             Attr('is_deleted').eq(False)
        )
        items = response.get('Items', [])

    # ── STEP 3: Query param filters ──────────────────────────────────────────
    query_params = event.get('queryStringParameters') or {}
    filter_type  = query_params.get('document_type', '').strip()
    filter_tag   = query_params.get('tag', '').strip()

    if filter_type:
        items = [i for i in items if i.get('document_type') == filter_type]
    if filter_tag:
        items = [i for i in items if filter_tag in i.get('tags', [])]

    # ── STEP 4: Sort ─────────────────────────────────────────────────────────
    sort_by = query_params.get('sort_by', 'upload_timestamp')
    if sort_by == 'document_type':
        items.sort(key=lambda x: x.get('document_type', ''))
    else:
        items.sort(key=lambda x: x.get('upload_timestamp', ''), reverse=True)

    # ── STEP 5: Audit log ────────────────────────────────────────────────────
    write_audit_log(employee_id, 'LIST', 'N/A')

    # ── STEP 6: Shape response ───────────────────────────────────────────────
    # FIX 1: added s3_key — frontend uses this to show the filename
    # FIX 2: decimal_clean — prevents JSON serialization crash on Decimal fields
    result = []
    for i in items:
        result.append({
            'document_id':      i.get('document_id'),
            'document_type':    i.get('document_type'),
            'employee_id':      i.get('employee_id'),
            'upload_timestamp': i.get('upload_timestamp'),
            'tags':             i.get('tags', []),
            'uploaded_by':      i.get('uploaded_by', ''),
            's3_key':           i.get('s3_key', ''),   # ← FIX 1: was missing
        })

    # FIX 2: clean Decimals before returning
    result = decimal_clean(result)

    # FIX 3: api_response must return a plain array in body, not wrapped.
    # If your utils.api_response wraps it like {"data": result} the frontend
    # won't see it. Return directly to be safe:
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin':  '*',
            'Access-Control-Allow-Headers': 'Authorization, Content-Type',
            'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
        },
        'body': json.dumps(result)   # plain array — NO wrapper object
    }