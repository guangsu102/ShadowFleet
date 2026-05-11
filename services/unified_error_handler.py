"""
统一错误处理策略

提供：
1. 统一的错误码体系
2. 错误分类（系统错误 vs 业务错误）
3. 用户友好的错误消息
4. 错误上下文追踪
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ErrorCategory(Enum):
    """错误分类"""
    SYSTEM = "system"          # 系统错误（如数据库连接失败）
    BUSINESS = "business"      # 业务错误（如资源不足）
    VALIDATION = "validation"  # 验证错误（如参数非法）
    EXTERNAL = "external"      # 外部服务错误（如 AWS API 失败）
    CONCURRENCY = "concurrency"  # 并发错误（如锁冲突）


class ErrorCode(Enum):
    """统一错误码"""

    # 系统错误 (1xxx)
    SYSTEM_INTERNAL_ERROR = (1000, "系统内部错误", ErrorCategory.SYSTEM)
    SYSTEM_DATABASE_ERROR = (1001, "数据库错误", ErrorCategory.SYSTEM)
    SYSTEM_NETWORK_ERROR = (1002, "网络错误", ErrorCategory.SYSTEM)
    SYSTEM_TIMEOUT = (1003, "操作超时", ErrorCategory.SYSTEM)
    SYSTEM_CONFIGURATION_ERROR = (1004, "配置错误", ErrorCategory.SYSTEM)

    # 业务错误 (2xxx)
    BUSINESS_RESOURCE_NOT_FOUND = (2000, "资源不存在", ErrorCategory.BUSINESS)
    BUSINESS_RESOURCE_EXHAUSTED = (2001, "资源已耗尽", ErrorCategory.BUSINESS)
    BUSINESS_RESOURCE_CONFLICT = (2002, "资源冲突", ErrorCategory.BUSINESS)
    BUSINESS_OPERATION_NOT_ALLOWED = (2003, "操作不允许", ErrorCategory.BUSINESS)
    BUSINESS_QUOTA_EXCEEDED = (2004, "配额超限", ErrorCategory.BUSINESS)

    # 验证错误 (3xxx)
    VALIDATION_INVALID_PARAMETER = (3000, "参数非法", ErrorCategory.VALIDATION)
    VALIDATION_MISSING_PARAMETER = (3001, "缺少必需参数", ErrorCategory.VALIDATION)
    VALIDATION_PARAMETER_OUT_OF_RANGE = (3002, "参数超出范围", ErrorCategory.VALIDATION)
    VALIDATION_INVALID_FORMAT = (3003, "格式错误", ErrorCategory.VALIDATION)

    # 外部服务错误 (4xxx)
    EXTERNAL_AWS_ERROR = (4000, "AWS 服务错误", ErrorCategory.EXTERNAL)
    EXTERNAL_CLOUDFLARE_ERROR = (4001, "Cloudflare 服务错误", ErrorCategory.EXTERNAL)
    EXTERNAL_XBOARD_ERROR = (4002, "Xboard 服务错误", ErrorCategory.EXTERNAL)
    EXTERNAL_SERVICE_UNAVAILABLE = (4003, "外部服务不可用", ErrorCategory.EXTERNAL)

    # 并发错误 (5xxx)
    CONCURRENCY_LOCK_TIMEOUT = (5000, "获取锁超时", ErrorCategory.CONCURRENCY)
    CONCURRENCY_LOCK_CONFLICT = (5001, "锁冲突", ErrorCategory.CONCURRENCY)
    CONCURRENCY_VERSION_CONFLICT = (5002, "版本冲突", ErrorCategory.CONCURRENCY)
    CONCURRENCY_RESOURCE_BUSY = (5003, "资源繁忙", ErrorCategory.CONCURRENCY)

    # Provisioning 错误 (6xxx)
    PROVISIONING_ASSET_SELECTION_FAILED = (6000, "资产选择失败", ErrorCategory.BUSINESS)
    PROVISIONING_NODE_REGISTRATION_FAILED = (6001, "节点注册失败", ErrorCategory.BUSINESS)
    PROVISIONING_DOMAIN_ALLOCATION_FAILED = (6002, "域名分配失败", ErrorCategory.BUSINESS)
    PROVISIONING_INSTANCE_LAUNCH_FAILED = (6003, "实例启动失败", ErrorCategory.EXTERNAL)
    PROVISIONING_DNS_SYNC_FAILED = (6004, "DNS 同步失败", ErrorCategory.EXTERNAL)
    PROVISIONING_READY_TIMEOUT = (6005, "就绪超时", ErrorCategory.SYSTEM)
    PROVISIONING_ROLLBACK_FAILED = (6006, "回滚失败", ErrorCategory.SYSTEM)

    def __init__(self, code: int, message: str, category: ErrorCategory) -> None:
        self.code = code
        self.message = message
        self.category = category


@dataclass(frozen=True)
class ErrorContext:
    """错误上下文"""
    error_code: ErrorCode
    user_message: str  # 用户友好的错误消息
    technical_details: str | None = None  # 技术细节（仅用于日志）
    suggestion: str | None = None  # 解决建议
    context: dict[str, Any] | None = None  # 额外的上下文信息
    original_exception: Exception | None = None  # 原始异常


class ShadowFleetError(Exception):
    """ShadowFleet 统一异常基类"""

    def __init__(self, error_context: ErrorContext) -> None:
        self.error_context = error_context
        super().__init__(error_context.user_message)

    @property
    def error_code(self) -> ErrorCode:
        return self.error_context.error_code

    @property
    def code(self) -> int:
        return self.error_context.error_code.code

    @property
    def category(self) -> ErrorCategory:
        return self.error_context.error_code.category

    @property
    def user_message(self) -> str:
        return self.error_context.user_message

    @property
    def technical_details(self) -> str | None:
        return self.error_context.technical_details

    @property
    def suggestion(self) -> str | None:
        return self.error_context.suggestion

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于 API 响应）"""
        return {
            "error_code": self.error_code.code,
            "error_name": self.error_code.name,
            "category": self.category.value,
            "message": self.user_message,
            "suggestion": self.suggestion,
            "context": self.error_context.context,
        }


class SystemError(ShadowFleetError):
    """系统错误"""
    pass


class BusinessError(ShadowFleetError):
    """业务错误"""
    pass


class ValidationError(ShadowFleetError):
    """验证错误"""
    pass


class ExternalServiceError(ShadowFleetError):
    """外部服务错误"""
    pass


class ConcurrencyError(ShadowFleetError):
    """并发错误"""
    pass


class ProvisioningError(ShadowFleetError):
    """Provisioning 错误"""
    pass


def create_error(
    error_code: ErrorCode,
    user_message: str | None = None,
    technical_details: str | None = None,
    suggestion: str | None = None,
    context: dict[str, Any] | None = None,
    original_exception: Exception | None = None,
) -> ShadowFleetError:
    """
    创建统一错误

    Args:
        error_code: 错误码
        user_message: 用户友好的错误消息（如果为 None，使用默认消息）
        technical_details: 技术细节
        suggestion: 解决建议
        context: 额外的上下文信息
        original_exception: 原始异常

    Returns:
        ShadowFleetError 或其子类
    """
    error_context = ErrorContext(
        error_code=error_code,
        user_message=user_message or error_code.message,
        technical_details=technical_details,
        suggestion=suggestion,
        context=context,
        original_exception=original_exception,
    )

    # 根据错误分类创建对应的异常类型
    if error_code.category == ErrorCategory.SYSTEM:
        return SystemError(error_context)
    elif error_code.category == ErrorCategory.BUSINESS:
        return BusinessError(error_context)
    elif error_code.category == ErrorCategory.VALIDATION:
        return ValidationError(error_context)
    elif error_code.category == ErrorCategory.EXTERNAL:
        return ExternalServiceError(error_context)
    elif error_code.category == ErrorCategory.CONCURRENCY:
        return ConcurrencyError(error_context)
    else:
        return ShadowFleetError(error_context)


# 便捷函数

def system_error(
    message: str,
    technical_details: str | None = None,
    original_exception: Exception | None = None,
) -> SystemError:
    """创建系统错误"""
    return create_error(
        ErrorCode.SYSTEM_INTERNAL_ERROR,
        user_message=message,
        technical_details=technical_details,
        original_exception=original_exception,
    )


def business_error(
    error_code: ErrorCode,
    message: str,
    suggestion: str | None = None,
    context: dict[str, Any] | None = None,
) -> BusinessError:
    """创建业务错误"""
    return create_error(
        error_code,
        user_message=message,
        suggestion=suggestion,
        context=context,
    )


def validation_error(
    parameter_name: str,
    reason: str,
    suggestion: str | None = None,
) -> ValidationError:
    """创建验证错误"""
    return create_error(
        ErrorCode.VALIDATION_INVALID_PARAMETER,
        user_message=f"参数 '{parameter_name}' 非法: {reason}",
        suggestion=suggestion,
        context={"parameter": parameter_name, "reason": reason},
    )


def external_service_error(
    service_name: str,
    operation: str,
    technical_details: str | None = None,
    original_exception: Exception | None = None,
) -> ExternalServiceError:
    """创建外部服务错误"""
    error_code_map = {
        "aws": ErrorCode.EXTERNAL_AWS_ERROR,
        "cloudflare": ErrorCode.EXTERNAL_CLOUDFLARE_ERROR,
        "xboard": ErrorCode.EXTERNAL_XBOARD_ERROR,
    }

    error_code = error_code_map.get(service_name.lower(), ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE)

    return create_error(
        error_code,
        user_message=f"{service_name} 服务操作失败: {operation}",
        technical_details=technical_details,
        suggestion="请稍后重试，如果问题持续存在，请联系管理员",
        context={"service": service_name, "operation": operation},
        original_exception=original_exception,
    )


def concurrency_error(
    resource_type: str,
    resource_id: str,
    reason: str,
) -> ConcurrencyError:
    """创建并发错误"""
    return create_error(
        ErrorCode.CONCURRENCY_RESOURCE_BUSY,
        user_message=f"资源 {resource_type}:{resource_id} 繁忙: {reason}",
        suggestion="请稍后重试",
        context={"resource_type": resource_type, "resource_id": resource_id, "reason": reason},
    )


def provisioning_error(
    error_code: ErrorCode,
    node_name: str,
    stage: str,
    technical_details: str | None = None,
    original_exception: Exception | None = None,
) -> ProvisioningError:
    """创建 Provisioning 错误"""
    return create_error(
        error_code,
        user_message=f"节点 '{node_name}' 在 {stage} 阶段失败",
        technical_details=technical_details,
        suggestion="请检查日志获取详细信息，或联系管理员",
        context={"node_name": node_name, "stage": stage},
        original_exception=original_exception,
    )
