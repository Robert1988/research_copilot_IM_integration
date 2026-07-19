"""
中间件
"""
import logging
import time
from typing import Callable
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import ClientDisconnect

from exceptions import SlackBotException

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """全局异常处理中间件"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            response = await call_next(request)
            return response
        except ClientDisconnect:
            # 客户端断开连接，这是正常情况，不需要记录错误
            logger.info(f"Client disconnected: {request.method} {request.url.path}")
            return JSONResponse(
                status_code=499,  # Client Closed Request
                content={"status": "client_disconnected"}
            )
        except SlackBotException as e:
            logger.error(f"SlackBotException: {e.message}", extra={
                "status_code": e.status_code,
                "details": e.details,
                "path": request.url.path,
                "method": request.method
            })
            return JSONResponse(
                status_code=e.status_code,
                content={
                    "error": True,
                    "message": e.message,
                    "details": e.details,
                    "status_code": e.status_code
                }
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", extra={
                "path": request.url.path,
                "method": request.method
            }, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={
                    "error": True,
                    "message": "Internal server error",
                    "details": {},
                    "status_code": 500
                }
            )

class LoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        # 记录请求信息
        logger.info(f"Request started: {request.method} {request.url.path}")
        
        response = await call_next(request)
        
        # 计算处理时间
        process_time = time.time() - start_time
        
        # 记录响应信息
        logger.info(f"Request completed: {request.method} {request.url.path} - "
                   f"Status: {response.status_code} - Time: {process_time:.3f}s")
        
        # 添加处理时间到响应头
        response.headers["X-Process-Time"] = str(process_time)
        
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全头中间件"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # 添加安全头
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        return response