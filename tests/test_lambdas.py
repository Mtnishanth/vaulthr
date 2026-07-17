import json
import pytest
import sys
import os
from unittest.mock import patch, MagicMock

# ── Helper ──────────────────────────────────
def make_event(employee_id, role, body=None, path_params=None):
    return {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "custom:employee_id": employee_id,
                    "custom:role": role
                }
            }
        },
        "body": json.dumps(body) if body else None,
        "pathParameters": path_params or {}
    }

# ── Mock utils module so Lambda imports don't fail ──
def setup_mocks():
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
    sys.modules["utils"] = mock_utils
    sys.modules["boto3"] = MagicMock()
    sys.modules["aws_xray_sdk"] = MagicMock()
    sys.modules["aws_xray_sdk.core"] = MagicMock()

setup_mocks()

# ══ UPLOAD LAMBDA TESTS ═════════════════════
class TestUploadValidation:

    def test_missing_employee_id_returns_400(self):
        sys.path.insert(0, "lambdas/upload")
        import importlib
        import lambda_function
        importlib.reload(lambda_function)
        event = make_event("EMP001", "Employee", body={
            "document_type": "payslip",
            "filename": "test.pdf"
            # employee_id intentionally missing
        })
        result = lambda_function.lambda_handler(event, {})
        assert result["statusCode"] == 400, \
            f"Expected 400 got {result['statusCode']}"

    def test_invalid_document_type_returns_400(self):
        sys.path.insert(0, "lambdas/upload")
        import importlib
        import lambda_function
        importlib.reload(lambda_function)
        event = make_event("EMP001", "Employee", body={
            "employee_id":   "EMP001",
            "document_type": "invalid_xyz",
            "filename":      "test.pdf"
        })
        result = lambda_function.lambda_handler(event, {})
        assert result["statusCode"] == 400, \
            f"Expected 400 got {result['statusCode']}"

    def test_employee_uploading_for_others_returns_403(self):
        sys.path.insert(0, "lambdas/upload")
        import importlib
        import lambda_function
        importlib.reload(lambda_function)
        event = make_event("EMP001", "Employee", body={
            "employee_id":   "EMP002",  # different from logged-in user
            "document_type": "payslip",
            "filename":      "test.pdf"
        })
        result = lambda_function.lambda_handler(event, {})
        assert result["statusCode"] == 403, \
            f"Expected 403 got {result['statusCode']}"

    def test_missing_jwt_returns_401(self):
        sys.path.insert(0, "lambdas/upload")
        import importlib
        import lambda_function
        importlib.reload(lambda_function)
        event = {
            "requestContext": {"authorizer": {"claims": {}}},
            "body": "{}"
        }
        result = lambda_function.lambda_handler(event, {})
        assert result["statusCode"] == 401, \
            f"Expected 401 got {result['statusCode']}"

# ══ DELETE LAMBDA TESTS ═════════════════════
class TestDeleteValidation:

    def test_missing_doc_id_returns_400(self):
        sys.path.insert(0, "lambdas/delete")
        import importlib
        if "lambda_function" in sys.modules:
            del sys.modules["lambda_function"]
        import lambda_function
        event = make_event("EMP001", "Employee", path_params={})
        result = lambda_function.lambda_handler(event, {})
        assert result["statusCode"] == 400, \
            f"Expected 400 got {result['statusCode']}"

    def test_manager_delete_returns_403(self):
        sys.path.insert(0, "lambdas/delete")
        import importlib
        if "lambda_function" in sys.modules:
            del sys.modules["lambda_function"]
        import lambda_function
        event = make_event("MGR001", "Manager",
                           path_params={"doc_id": "some-uuid"})
        result = lambda_function.lambda_handler(event, {})
        assert result["statusCode"] == 403, \
            f"Expected 403 got {result['statusCode']}"