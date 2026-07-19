"""
工具函数
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import HTTPException, Depends

from config import settings
from exceptions import AuthenticationError, ValidationError
from services.auth_service import AuthService

logger = logging.getLogger(__name__)
security = HTTPBearer()
auth_service = AuthService()


def verify_slack_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    """验证 Slack 请求签名"""
    try:
        # 检查时间戳（防止重放攻击）
        request_timestamp = int(timestamp)
        current_timestamp = int(datetime.now(timezone.utc).timestamp())
        
        if abs(current_timestamp - request_timestamp) > 300:  # 5分钟
            logger.warning("Request timestamp too old")
            return False
        
        # 构建签名字符串
        sig_basestring = f"v0:{timestamp}:{request_body.decode('utf-8')}"
        
        # 计算预期签名
        expected_signature = 'v0=' + hmac.new(
            settings.SLACK_SIGNING_SECRET.encode(),
            sig_basestring.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # 比较签名
        return hmac.compare_digest(expected_signature, signature)
    
    except Exception as e:
        logger.error(f"Error verifying Slack signature: {e}")
        return False


def format_error_response(message: str, details: Optional[Dict[str, Any]] = None, status_code: int = 400) -> Dict[str, Any]:
    """格式化错误响应"""
    return {
        "error": True,
        "message": message,
        "details": details or {},
        "status_code": status_code,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def format_success_response(data: Any, message: str = "Success") -> Dict[str, Any]:
    """格式化成功响应"""
    return {
        "error": False,
        "message": message,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def sanitize_user_input(text: str, max_length: int = 1000) -> str:
    """清理用户输入"""
    if not text:
        return ""
    
    # 移除潜在的恶意字符
    sanitized = text.strip()
    
    # 限制长度
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    
    return sanitized


def get_client_ip(request: Request) -> str:
    """获取客户端IP地址"""
    # 检查代理头
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    return request.client.host if request.client else "unknown"


def log_user_action(user_id: str, action: str, details: Optional[Dict[str, Any]] = None, request: Optional[Request] = None):
    """记录用户行为"""
    log_data = {
        "user_id": user_id,
        "action": action,
        "details": details or {},
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    if request:
        log_data.update({
            "ip_address": get_client_ip(request),
            "user_agent": request.headers.get("User-Agent", ""),
            "path": request.url.path,
            "method": request.method
        })
    
    logger.info(f"User action: {json.dumps(log_data)}")


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """获取当前认证用户"""
    try:
        token = credentials.credentials
        payload = auth_service.verify_token(token)
        
        if not payload:
            raise AuthenticationError("Invalid token")
        
        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationError("Invalid token payload")
        
        return {"user_id": user_id, "payload": payload}
    
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise AuthenticationError("Authentication failed")


def validate_slack_user_id(user_id: str) -> bool:
    """验证 Slack 用户 ID 格式"""
    if not user_id or not isinstance(user_id, str):
        return False
    
    # Slack 用户 ID 通常以 U 开头，后跟字母数字字符
    return user_id.startswith('U') and len(user_id) >= 9 and user_id[1:].isalnum()


def validate_slack_channel_id(channel_id: str) -> bool:
    """验证 Slack 频道 ID 格式"""
    if not channel_id or not isinstance(channel_id, str):
        return False
    
    # Slack 频道 ID 可以以 C（公共频道）、G（私有频道）或 D（DM）开头
    return (channel_id.startswith(('C', 'G', 'D')) and 
            len(channel_id) >= 9 and 
            channel_id[1:].isalnum())


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """截断文本"""
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def parse_slack_timestamp(ts: str) -> datetime:
    """解析 Slack 时间戳"""
    try:
        # Slack 时间戳格式：1234567890.123456
        timestamp = float(ts)
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)