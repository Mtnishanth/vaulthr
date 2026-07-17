import json
import pytest
import sys
import os

# ── Helper to build fake API Gateway event ──
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

# ── Upload Lambda Tests ──────────────────────
class TestUploadValidation:

    def test_missing_employee_id(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../lambdas/upload'))
        from lambda_function import lambda_handler
        event = make_event("EMP001", "Employee", body={
            "document_type": "payslip",
            "filename": "test.pdf"
        })
        result = lambda_handler(event, {})
        assert result["statusCode"] == 400

    def test_invalid_document_type(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../lambdas/upload'))
        from lambda_function import lambda_handler
        event = make_event("EMP001", "Employee", body={
            "employee_id": "EMP001",
            "document_type": "invalid_type",
            "filename": "test.pdf"
        })
        result = lambda_handler(event, {})
        assert result["statusCode"] == 400

    def test_employee_cannot_upload_for_others(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../lambdas/upload'))
        from lambda_function import lambda_handler
        event = make_event("EMP001", "Employee", body={
            "employee_id": "EMP002",
            "document_type": "payslip",
            "filename": "test.pdf"
        })
        result = lambda_handler(event, {})
        assert result["statusCode"] == 403

    def test_missing_jwt_returns_401(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../lambdas/upload'))
        from lambda_function import lambda_handler
        event = {
            "requestContext": {"authorizer": {"claims": {}}},
            "body": "{}"
        }
        result = lambda_handler(event, {})
        assert result["statusCode"] == 401

# ── Delete Lambda Tests ──────────────────────
class TestDeleteValidation:

    def test_missing_doc_id_returns_400(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../lambdas/delete'))
        from lambda_function import lambda_handler
        event = make_event("EMP001", "Employee", path_params={})
        result = lambda_handler(event, {})
        assert result["statusCode"] == 400

    def test_manager_cannot_delete_returns_403(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../lambdas/delete'))
        from lambda_function import lambda_handler
        event = make_event("MGR001", "Manager",
                           path_params={"doc_id": "some-uuid"})
        result = lambda_handler(event, {})
        assert result["statusCode"] == 403