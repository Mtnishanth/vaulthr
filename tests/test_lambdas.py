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