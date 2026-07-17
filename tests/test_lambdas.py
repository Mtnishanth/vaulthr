import json
import pytest
import sys
import os
from unittest.mock import patch, MagicMock

# ══ SET ENV VARS BEFORE ANY LAMBDA IMPORT ═══
# This fixes KeyError: 'BUCKET_NAME' and 'METADATA_TABLE'
os.environ['BUCKET_NAME']    = 'employee-document-vault'
os.environ['METADATA_TABLE'] = 'document_metadata'
os.environ['MANAGER_TABLE']  = 'manager_mapping'

# ══ MOCK ALL AWS DEPENDENCIES ════════════════
mock_utils = MagicMock()
mock_utils.decode_jwt_claims.side_effect = lambda event: \
    event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
mock_utils.get_user_info.side_effect = lambda claims: {
    "user_id":     claims.get("custom:employee_id", ""),
    "employee_id": claims.get("custom:employee_id", ""),
    "role":        claims.get("custom:role", ""),
    "groups":      ""
}
mock_utils.write_audit_log = MagicMock()
mock_utils.api_response.side_effect = lambda code, body: {
    "statusCode": code,
    "body": json.dumps(body)
}

sys.modules["utils"]              = mock_utils
sys.modules["boto3"]              = MagicMock()
sys.modules["aws_xray_sdk"]       = MagicMock()
sys.modules["aws_xray_sdk.core"]  = MagicMock()

# ══ HELPER ═══════════════════════════════════
def make_event(employee_id, role, body=None, path_params=None):
    return {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "custom:employee_id": employee_id,
                    "custom:role":        role
                }
            }
        },
        "body":            json.dumps(body) if body else None,
        "pathParameters":  path_params or {}
    }

# ══ UPLOAD TESTS ══════════════════════════════
class TestUploadValidation:

    def _get_handler(self):
        sys.path.insert(0, os.path.abspath("lambdas/upload"))
        if "lambda_function" in sys.modules:
            del sys.modules["lambda_function"]
        import lambda_function
        return lambda_function.lambda_handler

    def test_missing_employee_id_returns_400(self):
        handler = self._get_handler()
        event = make_event("EMP001", "Employee", body={
            "document_type": "payslip",
            "filename":      "test.pdf"
            # employee_id missing intentionally
        })
        result = handler(event, {})
        assert result["statusCode"] == 400, \
            f"Expected 400 but got {result['statusCode']}"

    def test_invalid_document_type_returns_400(self):
        handler = self._get_handler()
        event = make_event("EMP001", "Employee", body={
            "employee_id":   "EMP001",
            "document_type": "invalid_xyz",
            "filename":      "test.pdf"
        })
        result = handler(event, {})
        assert result["statusCode"] == 400, \
            f"Expected 400 but got {result['statusCode']}"

    def test_employee_uploading_for_others_returns_403(self):
        handler = self._get_handler()
        event = make_event("EMP001", "Employee", body={
            "employee_id":   "EMP002",
            "document_type": "payslip",
            "filename":      "test.pdf"
        })
        result = handler(event, {})
        assert result["statusCode"] == 403, \
            f"Expected 403 but got {result['statusCode']}"

    def test_missing_jwt_returns_401(self):
        handler = self._get_handler()
        event = {
            "requestContext": {"authorizer": {"claims": {}}},
            "body": "{}"
        }
        result = handler(event, {})
        assert result["statusCode"] == 401, \
            f"Expected 401 but got {result['statusCode']}"

# ══ DELETE TESTS ══════════════════════════════
class TestDeleteValidation:

    def _get_handler(self):
        sys.path.insert(0, os.path.abspath("lambdas/delete"))
        if "lambda_function" in sys.modules:
            del sys.modules["lambda_function"]
        import lambda_function
        return lambda_function.lambda_handler

    def test_missing_doc_id_returns_400(self):
        handler = self._get_handler()
        event = make_event("EMP001", "Employee", path_params={})
        result = handler(event, {})
        assert result["statusCode"] == 400, \
            f"Expected 400 but got {result['statusCode']}"

    def test_manager_delete_returns_403(self):
        handler = self._get_handler()
        event = make_event("MGR001", "Manager",
                           path_params={"doc_id": "some-uuid"})
        result = handler(event, {})
        assert result["statusCode"] == 403, \
            f"Expected 403 but got {result['statusCode']}"