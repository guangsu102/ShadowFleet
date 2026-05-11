"""
Tests for unified_error_handler module
"""
import pytest

from services.unified_error_handler import (
    BusinessError,
    ConcurrencyError,
    ErrorCategory,
    ErrorCode,
    ErrorContext,
    ExternalServiceError,
    ProvisioningError,
    ShadowFleetError,
    SystemError,
    ValidationError,
    business_error,
    concurrency_error,
    create_error,
    external_service_error,
    provisioning_error,
    system_error,
    validation_error,
)


class TestErrorCategory:
    """Tests for ErrorCategory enum"""

    def test_error_categories(self):
        """Test all error categories exist"""
        assert ErrorCategory.SYSTEM.value == "system"
        assert ErrorCategory.BUSINESS.value == "business"
        assert ErrorCategory.VALIDATION.value == "validation"
        assert ErrorCategory.EXTERNAL.value == "external"
        assert ErrorCategory.CONCURRENCY.value == "concurrency"


class TestErrorCode:
    """Tests for ErrorCode enum"""

    def test_system_error_codes(self):
        """Test system error codes"""
        assert ErrorCode.SYSTEM_INTERNAL_ERROR.code == 1000
        assert ErrorCode.SYSTEM_INTERNAL_ERROR.category == ErrorCategory.SYSTEM
        assert ErrorCode.SYSTEM_DATABASE_ERROR.code == 1001
        assert ErrorCode.SYSTEM_NETWORK_ERROR.code == 1002
        assert ErrorCode.SYSTEM_TIMEOUT.code == 1003
        assert ErrorCode.SYSTEM_CONFIGURATION_ERROR.code == 1004

    def test_business_error_codes(self):
        """Test business error codes"""
        assert ErrorCode.BUSINESS_RESOURCE_NOT_FOUND.code == 2000
        assert ErrorCode.BUSINESS_RESOURCE_NOT_FOUND.category == ErrorCategory.BUSINESS
        assert ErrorCode.BUSINESS_RESOURCE_EXHAUSTED.code == 2001
        assert ErrorCode.BUSINESS_RESOURCE_CONFLICT.code == 2002
        assert ErrorCode.BUSINESS_OPERATION_NOT_ALLOWED.code == 2003
        assert ErrorCode.BUSINESS_QUOTA_EXCEEDED.code == 2004

    def test_validation_error_codes(self):
        """Test validation error codes"""
        assert ErrorCode.VALIDATION_INVALID_PARAMETER.code == 3000
        assert ErrorCode.VALIDATION_INVALID_PARAMETER.category == ErrorCategory.VALIDATION
        assert ErrorCode.VALIDATION_MISSING_PARAMETER.code == 3001
        assert ErrorCode.VALIDATION_PARAMETER_OUT_OF_RANGE.code == 3002
        assert ErrorCode.VALIDATION_INVALID_FORMAT.code == 3003

    def test_external_error_codes(self):
        """Test external service error codes"""
        assert ErrorCode.EXTERNAL_AWS_ERROR.code == 4000
        assert ErrorCode.EXTERNAL_AWS_ERROR.category == ErrorCategory.EXTERNAL
        assert ErrorCode.EXTERNAL_CLOUDFLARE_ERROR.code == 4001
        assert ErrorCode.EXTERNAL_XBOARD_ERROR.code == 4002
        assert ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE.code == 4003

    def test_concurrency_error_codes(self):
        """Test concurrency error codes"""
        assert ErrorCode.CONCURRENCY_LOCK_TIMEOUT.code == 5000
        assert ErrorCode.CONCURRENCY_LOCK_TIMEOUT.category == ErrorCategory.CONCURRENCY
        assert ErrorCode.CONCURRENCY_LOCK_CONFLICT.code == 5001
        assert ErrorCode.CONCURRENCY_VERSION_CONFLICT.code == 5002
        assert ErrorCode.CONCURRENCY_RESOURCE_BUSY.code == 5003

    def test_provisioning_error_codes(self):
        """Test provisioning error codes"""
        assert ErrorCode.PROVISIONING_ASSET_SELECTION_FAILED.code == 6000
        assert ErrorCode.PROVISIONING_NODE_REGISTRATION_FAILED.code == 6001
        assert ErrorCode.PROVISIONING_DOMAIN_ALLOCATION_FAILED.code == 6002
        assert ErrorCode.PROVISIONING_INSTANCE_LAUNCH_FAILED.code == 6003
        assert ErrorCode.PROVISIONING_DNS_SYNC_FAILED.code == 6004
        assert ErrorCode.PROVISIONING_READY_TIMEOUT.code == 6005
        assert ErrorCode.PROVISIONING_ROLLBACK_FAILED.code == 6006


class TestErrorContext:
    """Tests for ErrorContext dataclass"""

    def test_error_context_minimal(self):
        """Test creating minimal error context"""
        context = ErrorContext(
            error_code=ErrorCode.SYSTEM_INTERNAL_ERROR,
            user_message="Something went wrong"
        )

        assert context.error_code == ErrorCode.SYSTEM_INTERNAL_ERROR
        assert context.user_message == "Something went wrong"
        assert context.technical_details is None
        assert context.suggestion is None
        assert context.context is None
        assert context.original_exception is None

    def test_error_context_full(self):
        """Test creating full error context"""
        original_exc = ValueError("test error")
        context = ErrorContext(
            error_code=ErrorCode.SYSTEM_DATABASE_ERROR,
            user_message="Database connection failed",
            technical_details="Connection timeout after 30s",
            suggestion="Check database server status",
            context={"host": "localhost", "port": 5432},
            original_exception=original_exc
        )

        assert context.error_code == ErrorCode.SYSTEM_DATABASE_ERROR
        assert context.user_message == "Database connection failed"
        assert context.technical_details == "Connection timeout after 30s"
        assert context.suggestion == "Check database server status"
        assert context.context == {"host": "localhost", "port": 5432}
        assert context.original_exception == original_exc

    def test_error_context_immutable(self):
        """Test that ErrorContext is immutable"""
        context = ErrorContext(
            error_code=ErrorCode.SYSTEM_INTERNAL_ERROR,
            user_message="Test"
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            context.user_message = "Modified"


class TestShadowFleetError:
    """Tests for ShadowFleetError base class"""

    def test_shadow_fleet_error_creation(self):
        """Test creating ShadowFleetError"""
        context = ErrorContext(
            error_code=ErrorCode.SYSTEM_INTERNAL_ERROR,
            user_message="Test error"
        )
        error = ShadowFleetError(context)

        assert error.error_context == context
        assert str(error) == "Test error"

    def test_shadow_fleet_error_properties(self):
        """Test ShadowFleetError properties"""
        context = ErrorContext(
            error_code=ErrorCode.BUSINESS_RESOURCE_NOT_FOUND,
            user_message="Resource not found",
            technical_details="ID: 123",
            suggestion="Check resource ID"
        )
        error = ShadowFleetError(context)

        assert error.error_code == ErrorCode.BUSINESS_RESOURCE_NOT_FOUND
        assert error.code == 2000
        assert error.category == ErrorCategory.BUSINESS
        assert error.user_message == "Resource not found"
        assert error.technical_details == "ID: 123"
        assert error.suggestion == "Check resource ID"

    def test_shadow_fleet_error_to_dict(self):
        """Test converting ShadowFleetError to dict"""
        context = ErrorContext(
            error_code=ErrorCode.VALIDATION_INVALID_PARAMETER,
            user_message="Invalid parameter",
            suggestion="Use valid value",
            context={"param": "age", "value": -1}
        )
        error = ShadowFleetError(context)

        result = error.to_dict()

        assert result["error_code"] == 3000
        assert result["error_name"] == "VALIDATION_INVALID_PARAMETER"
        assert result["category"] == "validation"
        assert result["message"] == "Invalid parameter"
        assert result["suggestion"] == "Use valid value"
        assert result["context"] == {"param": "age", "value": -1}


class TestErrorSubclasses:
    """Tests for error subclasses"""

    def test_system_error(self):
        """Test SystemError subclass"""
        context = ErrorContext(
            error_code=ErrorCode.SYSTEM_INTERNAL_ERROR,
            user_message="System error"
        )
        error = SystemError(context)

        assert isinstance(error, ShadowFleetError)
        assert isinstance(error, SystemError)

    def test_business_error(self):
        """Test BusinessError subclass"""
        context = ErrorContext(
            error_code=ErrorCode.BUSINESS_RESOURCE_NOT_FOUND,
            user_message="Business error"
        )
        error = BusinessError(context)

        assert isinstance(error, ShadowFleetError)
        assert isinstance(error, BusinessError)

    def test_validation_error(self):
        """Test ValidationError subclass"""
        context = ErrorContext(
            error_code=ErrorCode.VALIDATION_INVALID_PARAMETER,
            user_message="Validation error"
        )
        error = ValidationError(context)

        assert isinstance(error, ShadowFleetError)
        assert isinstance(error, ValidationError)

    def test_external_service_error(self):
        """Test ExternalServiceError subclass"""
        context = ErrorContext(
            error_code=ErrorCode.EXTERNAL_AWS_ERROR,
            user_message="External error"
        )
        error = ExternalServiceError(context)

        assert isinstance(error, ShadowFleetError)
        assert isinstance(error, ExternalServiceError)

    def test_concurrency_error(self):
        """Test ConcurrencyError subclass"""
        context = ErrorContext(
            error_code=ErrorCode.CONCURRENCY_LOCK_TIMEOUT,
            user_message="Concurrency error"
        )
        error = ConcurrencyError(context)

        assert isinstance(error, ShadowFleetError)
        assert isinstance(error, ConcurrencyError)

    def test_provisioning_error(self):
        """Test ProvisioningError subclass"""
        context = ErrorContext(
            error_code=ErrorCode.PROVISIONING_ASSET_SELECTION_FAILED,
            user_message="Provisioning error"
        )
        error = ProvisioningError(context)

        assert isinstance(error, ShadowFleetError)
        assert isinstance(error, ProvisioningError)


class TestCreateError:
    """Tests for create_error function"""

    def test_create_system_error(self):
        """Test creating system error"""
        error = create_error(
            ErrorCode.SYSTEM_DATABASE_ERROR,
            user_message="DB error"
        )

        assert isinstance(error, SystemError)
        assert error.code == 1001

    def test_create_business_error(self):
        """Test creating business error"""
        error = create_error(
            ErrorCode.BUSINESS_RESOURCE_EXHAUSTED,
            user_message="No resources"
        )

        assert isinstance(error, BusinessError)
        assert error.code == 2001

    def test_create_validation_error(self):
        """Test creating validation error"""
        error = create_error(
            ErrorCode.VALIDATION_MISSING_PARAMETER,
            user_message="Missing param"
        )

        assert isinstance(error, ValidationError)
        assert error.code == 3001

    def test_create_external_error(self):
        """Test creating external service error"""
        error = create_error(
            ErrorCode.EXTERNAL_CLOUDFLARE_ERROR,
            user_message="CF error"
        )

        assert isinstance(error, ExternalServiceError)
        assert error.code == 4001

    def test_create_concurrency_error(self):
        """Test creating concurrency error"""
        error = create_error(
            ErrorCode.CONCURRENCY_LOCK_CONFLICT,
            user_message="Lock conflict"
        )

        assert isinstance(error, ConcurrencyError)
        assert error.code == 5001

    def test_create_error_with_default_message(self):
        """Test creating error with default message"""
        error = create_error(ErrorCode.SYSTEM_TIMEOUT)

        assert error.user_message == "操作超时"

    def test_create_error_with_all_fields(self):
        """Test creating error with all fields"""
        original_exc = ValueError("original")
        error = create_error(
            ErrorCode.SYSTEM_NETWORK_ERROR,
            user_message="Network failed",
            technical_details="Timeout after 30s",
            suggestion="Check network",
            context={"host": "example.com"},
            original_exception=original_exc
        )

        assert error.user_message == "Network failed"
        assert error.technical_details == "Timeout after 30s"
        assert error.suggestion == "Check network"
        assert error.error_context.context == {"host": "example.com"}
        assert error.error_context.original_exception == original_exc


class TestConvenienceFunctions:
    """Tests for convenience functions"""

    def test_system_error_function(self):
        """Test system_error convenience function"""
        error = system_error("System failure")

        assert isinstance(error, SystemError)
        assert error.user_message == "System failure"
        assert error.code == 1000

    def test_system_error_with_details(self):
        """Test system_error with technical details"""
        original_exc = RuntimeError("test")
        error = system_error(
            "System failure",
            technical_details="Stack trace here",
            original_exception=original_exc
        )

        assert error.technical_details == "Stack trace here"
        assert error.error_context.original_exception == original_exc

    def test_business_error_function(self):
        """Test business_error convenience function"""
        error = business_error(
            ErrorCode.BUSINESS_RESOURCE_NOT_FOUND,
            "Resource missing",
            suggestion="Create resource first"
        )

        assert isinstance(error, BusinessError)
        assert error.user_message == "Resource missing"
        assert error.suggestion == "Create resource first"

    def test_validation_error_function(self):
        """Test validation_error convenience function"""
        error = validation_error(
            "age",
            "must be positive",
            suggestion="Use value > 0"
        )

        assert isinstance(error, ValidationError)
        assert "age" in error.user_message
        assert "must be positive" in error.user_message
        assert error.suggestion == "Use value > 0"
        assert error.error_context.context == {"parameter": "age", "reason": "must be positive"}

    def test_external_service_error_function_aws(self):
        """Test external_service_error for AWS"""
        error = external_service_error(
            "aws",
            "launch instance",
            technical_details="API error"
        )

        assert isinstance(error, ExternalServiceError)
        assert error.error_code == ErrorCode.EXTERNAL_AWS_ERROR
        assert "aws" in error.user_message.lower()
        assert "launch instance" in error.user_message

    def test_external_service_error_function_cloudflare(self):
        """Test external_service_error for Cloudflare"""
        error = external_service_error(
            "cloudflare",
            "create DNS record"
        )

        assert error.error_code == ErrorCode.EXTERNAL_CLOUDFLARE_ERROR

    def test_external_service_error_function_xboard(self):
        """Test external_service_error for Xboard"""
        error = external_service_error(
            "xboard",
            "register node"
        )

        assert error.error_code == ErrorCode.EXTERNAL_XBOARD_ERROR

    def test_external_service_error_function_unknown(self):
        """Test external_service_error for unknown service"""
        error = external_service_error(
            "unknown_service",
            "some operation"
        )

        assert error.error_code == ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE

    def test_concurrency_error_function(self):
        """Test concurrency_error convenience function"""
        error = concurrency_error(
            "node",
            "node-123",
            "locked by another process"
        )

        assert isinstance(error, ConcurrencyError)
        assert "node:node-123" in error.user_message
        assert "locked by another process" in error.user_message
        assert error.error_context.context == {
            "resource_type": "node",
            "resource_id": "node-123",
            "reason": "locked by another process"
        }

    def test_provisioning_error_function(self):
        """Test provisioning_error convenience function"""
        error = provisioning_error(
            ErrorCode.PROVISIONING_ASSET_SELECTION_FAILED,
            "test-node",
            "asset_selection",
            technical_details="No assets available"
        )

        assert isinstance(error, BusinessError)  # PROVISIONING_ASSET_SELECTION_FAILED is BUSINESS category
        assert "test-node" in error.user_message
        assert "asset_selection" in error.user_message
        assert error.technical_details == "No assets available"
        assert error.error_context.context == {"node_name": "test-node", "stage": "asset_selection"}

    def test_provisioning_error_with_original_exception(self):
        """Test provisioning_error with original exception"""
        original_exc = RuntimeError("EC2 error")
        error = provisioning_error(
            ErrorCode.PROVISIONING_DNS_SYNC_FAILED,
            "test-node",
            "dns_sync",
            original_exception=original_exc
        )

        assert error.error_context.original_exception == original_exc
