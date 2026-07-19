"""
自定义异常类
"""
from typing import Any, Dict, Optional


class SlackBotException(Exception):
    """基础异常类"""
    def __init__(self, message: str, status_code: int = 500, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class AuthenticationError(SlackBotException):
    """认证错误"""
    def __init__(self, message: str = "Authentication failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 401, details)


class AuthorizationError(SlackBotException):
    """授权错误"""
    def __init__(self, message: str = "Access denied", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 403, details)


class ValidationError(SlackBotException):
    """验证错误"""
    def __init__(self, message: str = "Validation failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 422, details)


class NotFoundError(SlackBotException):
    """资源未找到错误"""
    def __init__(self, message: str = "Resource not found", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 404, details)


class ConflictError(SlackBotException):
    """冲突错误"""
    def __init__(self, message: str = "Resource conflict", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 409, details)


class SlackAPIError(SlackBotException):
    """Slack API 错误"""
    def __init__(self, message: str = "Slack API error", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 502, details)


class DatabaseError(SlackBotException):
    """数据库错误"""
    def __init__(self, message: str = "Database operation failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 500, details)


class SubscriptionError(SlackBotException):
    """订阅相关错误"""
    def __init__(self, message: str = "Subscription error", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 400, details)


class UsageLimitError(SlackBotException):
    """使用限制错误"""
    def __init__(self, message: str = "Usage limit exceeded", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 429, details)


class PaymentError(SlackBotException):
    """支付错误"""
    def __init__(self, message: str = "Payment processing failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 402, details)