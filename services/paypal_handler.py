import os
import json
import base64
import asyncio
import uuid
from typing import Optional, Dict, Any
import aiohttp
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from config import settings
import logging
from bson import ObjectId
from database import get_database
# 在导入部分添加新的导入
from models import (
    PayPalOrderRequest, PayPalOrderResponse, PayPalCaptureResponse,
    PayPalErrorResponse, PayPalLink, PayPalAmount, PayPalCapture,
    PayPalPayments, PayPalPurchaseUnit, OrderType, DataAddonType
)

from services.config_user_plan import (
    SUBSCRIPTION_PLANS_CONFIG, DATA_ADDONS_CONFIG,
    SubscriptionPlanType as ConfigSubscriptionPlanType,
    DataAddonType as ConfigDataAddonType
)

# from src.validationCode import send_email  # Temporarily commented out

class PayPalHandler:
    """PayPal Payment Handler"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # PayPal Configuration
        self.environment = os.getenv("PAYPAL_ENVIRONMENT", "sandbox")  # sandbox or live
        
        # Set PayPal API base URL
        if self.environment == "live":
            self.base_url = "https://api-m.paypal.com"
            self.client_id = os.getenv("PAYPAL_CLIENT_ID_PROD")
            self.client_secret = os.getenv("PAYPAL_CLIENT_SECRET_PROD")
        else:
            self.base_url = "https://api-m.sandbox.paypal.com"
            self.client_id = os.getenv("PAYPAL_CLIENT_ID")
            self.client_secret = os.getenv("PAYPAL_CLIENT_SECRET")
        
        if not self.client_id or not self.client_secret:
            raise ValueError("PayPal client ID and secret must be set in environment variables")

        # Access token cache
        self._access_token = None
        self._token_expires_at = None
    
    async def _get_database(self):
        """获取数据库连接"""
        return await get_database()
    
    async def _send_email_placeholder(self, recipient_email: str, subject: str, body: str) -> bool:
        """临时邮件发送占位符函数"""
        # 这里可以集成实际的邮件发送服务，比如 SendGrid, AWS SES 等
        # 目前先记录日志，不实际发送邮件
        self.logger.info(f"Email would be sent to {recipient_email} with subject: {subject}")
        return True
    
    async def _get_orders_collection(self):
        """获取订单集合"""
        db = await self._get_database()
        return db["paypal_orders"]
    
    async def _get_users_collection(self):
        """获取用户集合"""
        db = await self._get_database()
        return db["users"]

    @classmethod
    def close_resources(cls):
        """Close shared resources"""
        if cls._mongo_client is not None:
            cls._mongo_client.close()
            cls._mongo_client = None

    async def get_access_token(self) -> str:
        """Get PayPal access token"""
        try:
            # Check if cached token is still valid
            if (self._access_token and self._token_expires_at and 
                datetime.now().timestamp() < self._token_expires_at):
                return self._access_token
            
            # Prepare authentication header
            auth_string = f"{self.client_id}:{self.client_secret}"
            auth_bytes = auth_string.encode('ascii')
            auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
            
            headers = {
                'Accept': 'application/json',
                'Accept-Language': 'en_US',
                'Authorization': f'Basic {auth_b64}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = 'grant_type=client_credentials'
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/v1/oauth2/token",
                    headers=headers,
                    data=data
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        self._access_token = result['access_token']
                        # Set token expiration time (expire 5 minutes early for safety)
                        expires_in = result.get('expires_in', 3600) - 300
                        self._token_expires_at = datetime.now().timestamp() + expires_in
                        
                        self.logger.info("PayPal access token obtained successfully")
                        return self._access_token
                    else:
                        error_text = await response.text()
                        self.logger.error(f"Failed to get PayPal access token: {response.status} - {error_text}")
                        raise Exception(f"Failed to get PayPal access token: {response.status}")
                        
        except Exception as e:
            self.logger.error(f"Exception getting PayPal access token: {str(e)}")
            raise

    async def create_order(self, order_request: PayPalOrderRequest, user_id: str) -> PayPalOrderResponse:
        """Create PayPal order - supports both one-time payments and subscriptions"""
        try:
            self.logger.info(f"Starting PayPal order creation for user: {user_id}")
            self.logger.info(f"Order request details - Type: {'Subscription' if order_request.is_subscription else 'One-time'}, "
                           f"Description: {order_request.description}")
            
            access_token = await self.get_access_token()
            self.logger.debug(f"Successfully obtained PayPal access token for order creation")
            
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}',
                'PayPal-Request-Id': f"{user_id}-{int(datetime.now().timestamp())}"
            }
            
            self.logger.debug(f"PayPal request headers prepared with Request-Id: {headers['PayPal-Request-Id']}")
            
            # 根据订单类型创建不同的PayPal订单
            if order_request.is_subscription:
                self.logger.info(f"Creating subscription order for user {user_id}")
                self.logger.debug(f"Subscription order metadata: {order_request.metadata}")
                # 创建订阅订单
                return await self._create_subscription_order(headers, order_request, user_id)
            else:
                self.logger.info(f"Creating one-time payment order for user {user_id}")
                self.logger.debug(f"One-time order metadata: {order_request.metadata}")
                # 创建一次性付款订单
                return await self._create_one_time_order(headers, order_request, user_id)
                        
        except Exception as e:
            self.logger.error(f"Exception creating PayPal order for user {user_id}: {str(e)}")
            self.logger.error(f"Order request that failed: {order_request}")
            raise

    def _determine_order_type(self, order_request: PayPalOrderRequest) -> str:
        """根据 subscription_plan_type 或 data_addon_type 判断订单类型"""
        if order_request.is_subscription and order_request.subscription_plan_type:
            # 订阅类型订单
            return "subscription_purchase"
        elif not order_request.is_subscription and order_request.data_addon_type:
            # 数据附加包订单
            return "addon_purchase"
        else:
            # 默认类型
            return "unknown"

    async def _create_one_time_order(self, headers: dict, order_request: PayPalOrderRequest, user_id: str) -> PayPalOrderResponse:
        """Create one-time order (for data addons)"""
        # 从配置中获取数据附加项信息
        plan_data = self._get_plan_data_from_config(order_request)
        
        # 检查是否有有效的配置数据，如果没有则返回失败
        if not plan_data or plan_data["type"] != "addon":
            error_msg = f"No valid addon configuration found for data_addon_type: {order_request.data_addon_type}"
            self.logger.error(error_msg)
            raise Exception(error_msg)
        
        # 使用配置中的数据
        amount = plan_data["price"]
        currency = plan_data["currency"]
        description = plan_data["description"]
        self.logger.info(f"Using addon config data: price={amount}, currency={currency}, description={description}")
        
        # 判断订单类型
        order_type = self._determine_order_type(order_request)
        
        # Build order data for one-time payment
        order_data = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "amount": {
                    "currency_code": currency,
                    "value": str(amount)
                },
                "description": description
            }],
            "application_context": {
                "return_url": order_request.return_url,
                "cancel_url": order_request.cancel_url,
                "brand_name": "AlignSpires",
                "landing_page": "BILLING",
                "user_action": "PAY_NOW"
            }
        }
        
        self.logger.info(f"Creating PayPal one-time order with data: {order_data}")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v2/checkout/orders",
                headers=headers,
                json=order_data
            ) as response:
                if response.status == 201:
                    result = await response.json()
                    
                    self.logger.info(f"PayPal one-time order creation response: {result}")

                    # Save order to database with enhanced data
                    order_doc = {
                        "order_id": result["id"],
                        "user_id": user_id,
                        "status": result["status"],
                        "amount": amount,
                        "currency": currency,
                        "description": description,
                        "order_type": order_type,  # 使用判断出的订单类型
                        "metadata": order_request.metadata,
                        "is_subscription": False,
                        "data_addon_type": order_request.data_addon_type,
                        "plan_config_data": plan_data,  # 保存配置数据
                        # 从 plan_data 中读取额外信息
                        "paypal_product_name": plan_data.get("paypal_product_name"),
                        "paypal_product_description": plan_data.get("paypal_product_description"),
                        "paypal_product_category": plan_data.get("paypal_product_category"),
                        "credits": plan_data.get("credits"),
                        "validity_days": plan_data.get("validity_days"),
                        "created_at": datetime.now(),
                        "updated_at": datetime.now(),
                        "paypal_response": result
                    }
                    orders_collection = await self._get_orders_collection()
                    await orders_collection.insert_one(order_doc)
                    
                    # Build response
                    links = [PayPalLink(**link) for link in result.get("links", [])]
                    
                    # Extract approval URL from links
                    approval_url = None
                    for link in result.get("links", []):
                        if link.get("rel") == "approve":
                            approval_url = link.get("href")
                            break
                    
                    response_data = PayPalOrderResponse(
                        id=result["id"],
                        status=result["status"],
                        links=links,
                        approval_url=approval_url
                    )
                    
                    self.logger.info(f"PayPal one-time order created successfully: {result['id']}")
                    return response_data
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to create PayPal one-time order: {response.status} - {error_text}")
                    raise Exception(f"Failed to create PayPal one-time order: {response.status}")

    async def _create_subscription_order(self, headers: dict, order_request: PayPalOrderRequest, user_id: str) -> PayPalOrderResponse:
        """Create subscription order (for subscription plans)"""
        # 从配置中获取订阅计划信息
        plan_data = self._get_plan_data_from_config(order_request)
        
        self.logger.info(f"Subscription plan data: {plan_data}")

        # 检查是否有有效的配置数据，如果没有则返回失败
        if not plan_data or plan_data["type"] != "subscription":
            error_msg = f"No valid subscription plan configuration found for subscription_plan_type: {order_request.subscription_plan_type}"
            self.logger.error(error_msg)
            raise Exception(error_msg)
        
        # 首先需要确保订阅计划存在，如果不存在则创建
        plan_id = await self._ensure_subscription_plan_exists(order_request, headers, plan_data)
        
        # Get user information from database
        user_info = await self._get_user_info(user_id)
        
        # 使用配置中的数据
        amount = plan_data["price"]
        currency = plan_data["currency"]
        description = plan_data["description"]
        self.logger.info(f"Using subscription config data: price={amount}, currency={currency}, description={description}")
        
        # 判断订单类型
        order_type = self._determine_order_type(order_request)
        
        # 获取计费周期，优先使用 plan_data 中的配置
        billing_cycles = plan_data.get("billing_cycles", 12)
        
        # 使用 UTC 时间，设置为当前时间加1分钟（确保是未来时间）
        from datetime import timezone, timedelta
        start_time = (datetime.now(timezone.utc) + timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # Build subscription data
        subscription_data = {
            "plan_id": plan_id,
            "start_time": start_time,  # 5分钟后开始，第一期费用通过 setup_fee 立即收取
            "subscriber": {
                "name": {
                    "given_name": user_info["first_name"],
                    "surname": user_info["last_name"]
                },
                "email_address": user_info["email"]
            },
            "application_context": {
                "brand_name": "AlignSpires",
                "locale": "en-US",
                "shipping_preference": "NO_SHIPPING",
                "user_action": "SUBSCRIBE_NOW",
                "payment_method": {
                    "payer_selected": "PAYPAL",
                    "payee_preferred": "IMMEDIATE_PAYMENT_REQUIRED"
                },
                "return_url": order_request.return_url,
                "cancel_url": order_request.cancel_url
            },
            "custom_id": f"{user_id}:{order_request.subscription_plan_type}"
        }
        
        self.logger.info(f"Creating subscription with custom_id: {user_id}:{order_request.subscription_plan_type}")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/billing/subscriptions",
                headers=headers,
                json=subscription_data
            ) as response:
                if response.status == 201:
                    result = await response.json()
                    
                    self.logger.info(f"PayPal subscription creation response: {result}")

                    # Get user document to obtain slack_user_id
                    from services.database_service import DatabaseService
                    db_service = DatabaseService()
                    user = await db_service.get_user_by_id(user_id)
                    slack_user_id = user.slack_user_id if user else None

                    # Save subscription order to database
                    order_doc = {
                        "order_id": result["id"],
                        "user_id": user_id,
                        "slack_user_id": slack_user_id,  # 添加这个字段
                        "status": result["status"],
                        "amount": amount,
                        "currency": currency,
                        "description": description,
                        "order_type": order_type,  # 使用判断出的订单类型
                        "metadata": order_request.metadata,
                        "is_subscription": True,
                        "subscription_plan_id": plan_id,
                        "subscription_plan_type": order_request.subscription_plan_type,
                        "plan_config_data": plan_data,  # 保存配置数据
                        "billing_cycles": billing_cycles,  # 使用配置中的计费周期
                        # 从 plan_data 中读取额外信息
                        "paypal_plan_name": plan_data.get("paypal_plan_name"),
                        "paypal_plan_description": plan_data.get("paypal_plan_description"),
                        "paypal_product_category": plan_data.get("paypal_product_category"),
                        "billing_frequency": plan_data.get("billing_frequency"),
                        "trial_period_days": plan_data.get("trial_period_days"),
                        "setup_fee": 0,
                        "created_at": datetime.now(),
                        "updated_at": datetime.now(),
                        "paypal_response": result
                    }
                    orders_collection = await self._get_orders_collection()
                    await orders_collection.insert_one(order_doc)
                    
                    # Build response
                    links = [PayPalLink(**link) for link in result.get("links", [])]
                    
                    # Extract approval URL from links
                    approval_url = None
                    for link in result.get("links", []):
                        if link.get("rel") == "approve":
                            approval_url = link.get("href")
                            break
                    
                    response_data = PayPalOrderResponse(
                        id=result["id"],
                        status=result["status"],
                        links=links,
                        approval_url=approval_url
                    )
                    
                    self.logger.info(f"PayPal subscription created successfully: {result['id']}")
                    return response_data
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to create PayPal subscription: {response.status} - {error_text}")
                    raise Exception(f"Failed to create PayPal subscription: {response.status}")

    async def _ensure_product_exists(self, order_request: PayPalOrderRequest, headers: dict) -> str:
        """Ensure product exists in PayPal, create if not exists based on order type"""
        # 根据订单类型确定产品类型
        order_type = self._determine_order_type(order_request)
        metadata = order_request.metadata or {}
        
        if order_type == "subscription_purchase":
            # 订阅产品
            plan_type = order_request.subscription_plan_type or "base"
            product_key = f"alignspires_subscription_{plan_type}"
            product_id = f"alignspires_subscription_{plan_type}_product"
            product_name = f"AlignSpires {plan_type.title()} Subscription"
            product_description = f"AlignSpires {plan_type.title()} plan subscription service"
        elif order_type == "addon_purchase":
            # 数据包产品
            addon_type = order_request.data_addon_type or "basic"
            product_key = f"alignspires_addon_{addon_type}"
            product_id = f"alignspires_addon_{addon_type}_product"
            product_name = f"AlignSpires {addon_type.title()} Data Package"
            product_description = f"AlignSpires {addon_type.title()} data package addon"
        else:
            # 默认产品
            product_key = "alignspires_default"
            product_id = "alignspires_default_product"
            product_name = "AlignSpires Service"
            product_description = "AlignSpires AI-powered platform service"
        
        # 检查产品是否已存在
        cached_product_id = await self._get_cached_product_id(product_key)
        if cached_product_id:
            return cached_product_id
        
        # 创建产品
        product_data = {
            "id": product_id,
            "name": product_name,
            "description": product_description,
            "type": "SERVICE",
            "category": "SOFTWARE"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/catalogs/products",
                headers=headers,
                json=product_data
            ) as response:
                if response.status == 201:
                    result = await response.json()
                    created_product_id = result["id"]
                    
                    # 缓存产品ID
                    await self._cache_product_id(product_key, created_product_id)
                    
                    self.logger.info(f"PayPal product created: {created_product_id}")
                    return created_product_id
                elif response.status == 422:
                    # 处理重复产品ID的情况
                    error_text = await response.text()
                    self.logger.warning(f"Product already exists in PayPal: {product_id}, using existing product")
                    
                    # 缓存现有产品ID
                    await self._cache_product_id(product_key, product_id)
                    
                    return product_id
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to create PayPal product: {response.status} - {error_text}")
                    raise Exception(f"Failed to create PayPal product: {response.status}")

    async def _get_cached_plan_id(self, plan_key: str) -> Optional[str]:
        """Get cached plan ID from database"""
        try:
            db = await self._get_database()
            cached_plan = await db.paypal_plans.find_one({"plan_key": plan_key,
                "environment": self.environment})
            return cached_plan["plan_id"] if cached_plan else None
        except Exception:
            return None

    async def _cache_plan_id(self, plan_key: str, plan_id: str):
        """Cache plan ID in database"""
        try:
            db = await self._get_database()
            await db.paypal_plans.update_one(
                {"plan_key": plan_key, "environment": self.environment},
                {"$set": {
                    "plan_id": plan_id,
                    "environment": self.environment,
                    "created_at": datetime.now()
                }},
                upsert=True
            )
        except Exception as e:
            self.logger.error(f"Failed to cache plan ID: {str(e)}")

    async def _get_cached_product_id(self, product_key: str) -> Optional[str]:
        """Get cached product ID from database"""
        try:
            db = await self._get_database()
            cached_product = await db.paypal_products.find_one({"product_key": product_key, "environment": self.environment})
            return cached_product["product_id"] if cached_product else None
        except Exception:
            return None

    async def _cache_product_id(self, product_key: str, product_id: str):
        """Cache product ID in database"""
        try:
            db = await self._get_database()
            await db.paypal_products.update_one(
                {"product_key": product_key, "environment": self.environment},
                {"$set": {
                    "product_id": product_id,
                    "environment": self.environment,
                    "created_at": datetime.now()
                }},
                upsert=True
            )
        except Exception as e:
            self.logger.error(f"Failed to cache product ID: {str(e)}")

    async def _verify_plan_exists(self, headers: dict, plan_id: str) -> bool:
        """Verify a PayPal plan exists in the current environment"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/v1/billing/plans/{plan_id}",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        return True
                    else:
                        error_text = await response.text()
                        self.logger.warning(
                            f"Plan verification failed for {plan_id}: {response.status} - {error_text}"
                        )
                        return False
        except Exception as e:
            self.logger.error(f"Exception verifying plan existence: {str(e)}")
            return False

    async def _ensure_subscription_plan_exists(self, order_request: PayPalOrderRequest, headers: dict, plan_data: dict) -> str:
        """Ensure subscription plan exists in PayPal, create if not exists"""
        try:
            # 生成计划的唯一键
            plan_type = order_request.subscription_plan_type or "base"
            plan_key = f"alignspires_subscription_{plan_type}"
            
            # 检查计划是否已存在
            cached_plan_id = await self._get_cached_plan_id(plan_key)
            if cached_plan_id:
                # 在当前环境验证计划是否真实存在
                if await self._verify_plan_exists(headers, cached_plan_id):
                    return cached_plan_id
                else:
                    self.logger.warning(
                        f"Cached plan_id {cached_plan_id} not found in environment '{self.environment}', will recreate"
                    )
                    # 清理当前环境下的无效缓存
                    try:
                        await self.db.paypal_plans.delete_one({
                            "plan_key": plan_key,
                            "environment": self.environment
                        })
                    except Exception as e:
                        self.logger.error(f"Failed to delete invalid cached plan: {str(e)}")   
                    
            # 确保产品存在
            product_id = await self._ensure_product_exists(order_request, headers)
            
            # 从 plan_data 获取配置信息
            amount = plan_data["price"]
            currency = plan_data["currency"]
            description = plan_data["description"]
            billing_frequency_config = plan_data.get("billing_frequency", {"interval_unit": "MONTH", "interval_count": 1})
            billing_cycles = plan_data.get("billing_cycles", 12)
            trial_period_days = plan_data.get("trial_period_days", 0)
            
            # 构建计费周期配置
            billing_cycles_config = []
            billing_cycles_config.append({
                "frequency": {
                    "interval_unit": billing_frequency_config.get("interval_unit", "MONTH"),
                    "interval_count": billing_frequency_config.get("interval_count", 1)
                },
                "tenure_type": "REGULAR",
                "sequence": 2 if trial_period_days > 0 else 1,
                "total_cycles": 12,  # 12个月，一年订阅周期
                "pricing_scheme": {
                    "fixed_price": {
                        "value": str(amount),
                        "currency_code": currency
                    }
                }
            })
            
            # 构建订阅计划数据
            plan_data_payload = {
                "product_id": product_id,
                "name": plan_data.get("paypal_plan_name", f"AlignSpires {plan_type.title()} Plan"),
                "description": plan_data.get("paypal_plan_description", description),
                "status": "ACTIVE",
                "billing_cycles": billing_cycles_config,
                "payment_preferences": {
                    "auto_bill_outstanding": True,
                    "setup_fee": {
                        "value": 0,  # 第一期费用作为设置费立即收取
                        "currency_code": currency
                    },
                    "setup_fee_failure_action": "CANCEL",  # 如果设置费支付失败，取消订阅
                    "payment_failure_threshold": 3
                },
                "taxes": {
                    "percentage": "0",
                    "inclusive": False
                }
            }
            
            # 创建订阅计划
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/v1/billing/plans",
                    headers=headers,
                    json=plan_data_payload
                ) as response:
                    if response.status == 201:
                        result = await response.json()
                        created_plan_id = result["id"]
                        
                        # 缓存计划ID（按环境维度）
                        await self._cache_plan_id(plan_key, created_plan_id)
                        
                        self.logger.info(f"PayPal subscription plan created: {created_plan_id}")
                        return created_plan_id
                    else:
                        error_text = await response.text()
                        self.logger.error(f"Failed to create PayPal subscription plan: {response.status} - {error_text}")
                        raise Exception(f"Failed to create PayPal subscription plan: {response.status}")
                        
        except Exception as e:
            self.logger.error(f"Error ensuring subscription plan exists: {str(e)}")
            raise

    async def _get_user_info(self, user_id: str) -> dict:
        """Get user information from database"""
        try:
            user_object_id = ObjectId(user_id)
            users_collection = await self._get_users_collection()
            user_doc = await users_collection.find_one({"_id": user_object_id})
            
            if not user_doc:
                self.logger.error(f"User not found: {user_id}")
                raise Exception(f"User not found: {user_id}")
            
            # 提取用户信息，提供默认值以防字段缺失
            user_email = user_doc.get("email")
            if not user_email:
                # 使用更真实的邮箱格式，避免PayPal拒绝example.com域名
                user_email = f"user_{user_id[:8]}@alignspires.com"
            
            user_info = {
                "first_name": user_doc.get("first_name", "User"),
                "last_name": user_doc.get("last_name", "Name"),
                "email": user_email,
                "full_name": user_doc.get("full_name", f"{user_doc.get('first_name', 'User')} {user_doc.get('last_name', 'Name')}")
            }
            
            # 如果没有真实邮箱，记录警告但不抛出异常
            if not user_doc.get("email"):
                self.logger.warning(f"User {user_id} has no email, using placeholder: {user_info['email']}")
            
            self.logger.info(f"Retrieved user info for user: {user_id}")
            return user_info
            
        except Exception as e:
            self.logger.error(f"Exception getting user info: {str(e)}")
            raise

    async def capture_order(self, order_id: str, user_id: str) -> PayPalCaptureResponse:
        """Capture PayPal order payment"""
        try:
            # 首先检查订单类型
            orders_collection = await self._get_orders_collection()
            order_doc = await orders_collection.find_one(
                {"order_id": order_id, "user_id": user_id}
            )
            
            self.logger.info(f"order_doc:{order_doc}")

            if not order_doc:
                raise Exception(f"Order not found: {order_id}")
            
            is_subscription = order_doc.get("is_subscription", False)
            
            if is_subscription:
                # 订阅订单：检查订阅状态，不需要手动 capture
                return await self._handle_subscription_activation(order_id, user_id, order_doc)
            else:
                # 普通订单：使用现有的 capture 逻辑
                return await self._capture_regular_order(order_id, user_id, order_doc)
                
        except Exception as e:
            self.logger.error(f"Exception capturing PayPal order: {str(e)}")
            raise

    async def _handle_subscription_activation(self, subscription_id: str, user_id: str, order_doc: dict) -> PayPalCaptureResponse:
        """Handle subscription activation (no manual capture needed)"""
        try:
            self.logger.info(f"Handling subscription activation for subscription_id: {subscription_id}, user_id: {user_id}")
            
            access_token = await self.get_access_token()
            
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}'
            }
            
            # 获取订阅状态
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/v1/billing/subscriptions/{subscription_id}",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        
                        self.logger.info(f"PayPal subscription status: {result.get('status')}")
                        
                        # 更新订阅状态
                        orders_collection = await self._get_orders_collection()
                        await orders_collection.update_one(
                            {"order_id": subscription_id, "user_id": user_id},
                            {
                                "$set": {
                                    "status": result["status"],
                                    "updated_at": datetime.now(),
                                    "subscription_response": result
                                }
                            }
                        )
                        
                        # 无论订阅状态如何，都尝试处理订阅激活逻辑
                        # 因为用户已经完成了支付流程
                        await self._process_subscription_activation_directly(order_doc, user_id, subscription_id)
                        
                        # 构建兼容的响应格式
                        response_data = PayPalCaptureResponse(
                            id=result["id"],
                            status=result["status"],
                            purchase_units=[]  # 订阅没有 purchase_units
                        )
                        
                        self.logger.info(f"PayPal subscription processed: {subscription_id}")
                        return response_data
                    else:
                        error_text = await response.text()
                        self.logger.error(f"Failed to get subscription status: {response.status} - {error_text}")
                        
                        # 即使无法获取PayPal状态，也尝试处理订阅激活
                        # 因为用户已经完成了支付流程
                        self.logger.info("Attempting to process subscription activation despite PayPal API error")
                        await self._process_subscription_activation_directly(order_doc, user_id, subscription_id)
                        
                        # 返回一个基本的响应
                        response_data = PayPalCaptureResponse(
                            id=subscription_id,
                            status="PROCESSED",
                            purchase_units=[]
                        )
                        return response_data
                        
        except Exception as e:
            self.logger.error(f"Exception handling subscription activation: {str(e)}")
            
            # 即使出现异常，也尝试处理订阅激活
            try:
                self.logger.info("Attempting to process subscription activation despite exception")
                await self._process_subscription_activation_directly(order_doc, user_id, subscription_id)
            except Exception as inner_e:
                self.logger.error(f"Failed to process subscription activation directly: {str(inner_e)}")
            
            raise

    async def _process_subscription_activation_directly(self, order_doc: dict, user_id: str, subscription_id: str):
        """直接处理订阅激活逻辑，不依赖PayPal webhook"""
        try:
            self.logger.info(f"Processing subscription activation directly for user {user_id}")
            
            # 从订单文档中获取订阅计划类型
            subscription_plan_type = order_doc.get("subscription_plan_type")
            if not subscription_plan_type:
                self.logger.error("No subscription_plan_type found in order document")
                return
            
            self.logger.info(f"Subscription plan type: {subscription_plan_type}")
            
            # 映射计划类型到数据库枚举
            from models import SubscriptionPlan
            if subscription_plan_type == "free":
                plan = SubscriptionPlan.FREE
            elif subscription_plan_type == "base":
                plan = SubscriptionPlan.BASE
            elif subscription_plan_type == "pro":
                plan = SubscriptionPlan.PRO
            else:
                self.logger.error(f"Unknown subscription plan type: {subscription_plan_type}")
                return
            
            # 确保使用枚举的值而不是枚举对象本身
            plan_value = plan.value
            self.logger.info(f"Using plan value: {plan_value} (from enum {plan})")
            
            self.logger.info(f"Mapped plan type '{subscription_plan_type}' to '{plan}'")
            
            # 更新用户订阅
            from services.subscription_service import subscription_service
            result = await subscription_service.create_or_update_subscription(
                user_id=user_id,
                plan=plan,
                payment_method="paypal",
                external_subscription_id=subscription_id
            )
            
            self.logger.info(f"Subscription service result: {result}")
            
            if result["success"]:
                self.logger.info(f"Successfully activated subscription for user {user_id}")
                
                # 发送DM通知
                await self._send_subscription_notification(user_id, plan, result["is_new_subscription"])
            else:
                self.logger.error(f"Failed to activate subscription for user {user_id}: {result}")
                
        except Exception as e:
            self.logger.error(f"Error processing subscription activation directly: {str(e)}")
            raise
    
    async def _send_subscription_notification(self, user_id: str, plan, is_new_subscription: bool):
        """发送订阅通知到Slack"""
        try:
            self.logger.info(f"Sending subscription notification to user {user_id}")
            
            # 获取用户的Slack ID
            from services.database_service import DatabaseService
            db = DatabaseService()
            user = await db.get_user_by_id(user_id)
            
            if not user or not user.slack_user_id:
                self.logger.error(f"User {user_id} not found or missing Slack user ID")
                return
            
            self.logger.info(f"Found user with Slack ID: {user.slack_user_id}")
            
            # 确定计划名称
            from models import SubscriptionPlan
            if plan == SubscriptionPlan.FREE:
                plan_name = "Free Plan"
            elif plan == SubscriptionPlan.BASE:
                plan_name = "Base Plan"
            elif plan == SubscriptionPlan.PRO:
                plan_name = "Premium Plan"
            else:
                plan_name = "Unknown Plan"
            
            # 构建消息
            if is_new_subscription:
                message = f"🎉 Congratulations! Your {plan_name} subscription has been successfully activated!"
            else:
                message = f"🔄 Your {plan_name} subscription has been updated! Your payment has been processed successfully."
            
            # 发送DM
            from services.slack_service import slack_service
            self.logger.info(f"Sending DM to user {user.slack_user_id}: {message}")
            await slack_service.send_direct_message(user.slack_user_id, message, team_id=user.slack_team_id)
            self.logger.info(f"Successfully sent subscription notification to user {user_id}")
            
        except Exception as e:
            self.logger.error(f"Error sending subscription notification: {str(e)}")

    async def _capture_regular_order(self, order_id: str, user_id: str, order_doc: dict) -> PayPalCaptureResponse:
        """Capture regular (non-subscription) order"""
        try:
            access_token = await self.get_access_token()
            
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}',
                'PayPal-Request-Id': f"{user_id}-capture-{int(datetime.now().timestamp())}"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/v2/checkout/orders/{order_id}/capture",
                    headers=headers,
                    json={}
                ) as response:
                    if response.status == 201:
                        result = await response.json()
                        
                        # Update order status in database
                        orders_collection = await self._get_orders_collection()
                        await orders_collection.update_one(
                            {"order_id": order_id, "user_id": user_id},
                            {
                                "$set": {
                                    "status": result["status"],
                                    "updated_at": datetime.now(),
                                    "capture_response": result
                                }
                            }
                        )
                        
                        # Execute corresponding business logic based on order type
                        if order_doc and order_doc.get("order_type"):
                            asyncio.create_task(self._execute_business_logic(order_doc, user_id))
                        
                        # Build response
                        purchase_units = []
                        for unit in result.get("purchase_units", []):
                            captures = []
                            for capture in unit.get("payments", {}).get("captures", []):
                                amount = PayPalAmount(
                                    currency_code=capture["amount"]["currency_code"],
                                    value=capture["amount"]["value"]
                                )
                                captures.append(PayPalCapture(
                                    id=capture["id"],
                                    status=capture["status"],
                                    amount=amount
                                ))
                            
                            payments = PayPalPayments(captures=captures)
                            purchase_units.append(PayPalPurchaseUnit(payments=payments))
                        
                        response_data = PayPalCaptureResponse(
                            id=result["id"],
                            status=result["status"],
                            purchase_units=purchase_units
                        )
                        
                        self.logger.info(f"PayPal order captured successfully: {order_id}")
                        return response_data
                    else:
                        error_text = await response.text()
                        self.logger.error(f"Failed to capture PayPal order: {response.status} - {error_text}")
                        raise Exception(f"Failed to capture PayPal order: {response.status}")
                        
        except Exception as e:
            self.logger.error(f"Exception capturing regular PayPal order: {str(e)}")
            raise

    async def _execute_business_logic(self, order_doc: dict, user_id: str):
        """Execute corresponding business logic based on order type"""
        try:
            
            user_plan_manager = UserPlanManager()
            
            order_type = order_doc.get("order_type")
            metadata = order_doc.get("metadata", {})
            
            if order_type == "subscription_purchase":
                plan_type = SubscriptionPlanType(metadata.get("plan_type"))
                await user_plan_manager.execute_subscription_purchase(
                    user_id, plan_type, order_doc["order_id"],order_doc
                )
                
            elif order_type == "subscription_upgrade":
                new_plan_type = SubscriptionPlanType(metadata.get("new_plan_type"))
                await user_plan_manager.execute_subscription_upgrade(
                    user_id, new_plan_type, order_doc["order_id"]
                )
                
            elif order_type == "addon_purchase":
                # 修复：从 order_doc 中的 data_addon_type 字段获取 addon 类型，而不是从 metadata
                addon_type_str = order_doc.get("data_addon_type")
                if not addon_type_str:
                    raise ValueError("Missing data_addon_type in order document")
                
                addon_type = DataAddonType(addon_type_str)
                await user_plan_manager.execute_addon_purchase(
                    user_id, addon_type, order_doc["order_id"]
                )
                
            self.logger.info(f"Business logic executed successfully for order {order_doc['order_id']}")
            
        except Exception as e:
            self.logger.error(f"Failed to execute business logic: {str(e)}")
            # Consider marking the order as requiring manual processing
            orders_collection = await self._get_orders_collection()
            await orders_collection.update_one(
                {"order_id": order_doc["order_id"]},
                {"$set": {"business_logic_failed": True, "error_message": str(e)}}
            )
            raise

    async def get_order_details(self, order_id: str, user_id: str) -> PayPalOrderResponse:
        """Get PayPal order details"""
        try:
            access_token = await self.get_access_token()
            
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/v2/checkout/orders/{order_id}",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        
                        # Update order information in database
                        orders_collection = await self._get_orders_collection()
                        await orders_collection.update_one(
                            {"order_id": order_id, "user_id": user_id},
                            {
                                "$set": {
                                    "status": result["status"],
                                    "updated_at": datetime.now(),
                                    "latest_response": result
                                }
                            }
                        )
                        
                        # Build response
                        links = [PayPalLink(**link) for link in result.get("links", [])]
                        response_data = PayPalOrderResponse(
                            id=result["id"],
                            status=result["status"],
                            links=links
                        )
                        
                        self.logger.info(f"PayPal order details retrieved successfully: {order_id}")
                        return response_data
                    else:
                        error_text = await response.text()
                        self.logger.error(f"Failed to get PayPal order details: {response.status} - {error_text}")
                        raise Exception(f"Failed to get PayPal order details: {response.status}")
                        
        except Exception as e:
            self.logger.error(f"Exception getting PayPal order details: {str(e)}")
            raise

    async def get_subscription_details(self, subscription_id: str, user_id: str) -> PayPalOrderResponse:
        """Get PayPal subscription details"""
        try:
            access_token = await self.get_access_token()
            
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/v1/billing/subscriptions/{subscription_id}",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        
                        # Update subscription information in database
                        orders_collection = await self._get_orders_collection()
                        await orders_collection.update_one(
                            {"order_id": subscription_id, "user_id": user_id},
                            {
                                "$set": {
                                    "status": result["status"],
                                    "updated_at": datetime.now(),
                                    "latest_response": result
                                }
                            }
                        )
                        
                        # Build response - adapt subscription response to order response format
                        # For subscriptions, we need to create compatible links
                        links = []
                        if "links" in result:
                            links = [PayPalLink(**link) for link in result["links"]]
                        
                        response_data = PayPalOrderResponse(
                            id=result["id"],
                            status=result["status"],
                            links=links
                        )
                        
                        self.logger.info(f"PayPal subscription details retrieved successfully: {subscription_id}")
                        return response_data
                    else:
                        error_text = await response.text()
                        self.logger.error(f"Failed to get PayPal subscription details: {response.status} - {error_text}")
                        raise Exception(f"Failed to get PayPal subscription details: {response.status}")
                        
        except Exception as e:
            self.logger.error(f"Exception getting PayPal subscription details: {str(e)}")
            raise

    async def cancel_order(self, order_id: str, user_id: str) -> bool:
        """Cancel PayPal order or subscription"""
        try:
            # Get order information from database
            orders_collection = await self._get_orders_collection()
            order_doc = await orders_collection.find_one(
                {"order_id": order_id, "user_id": user_id}
            )
            
            if not order_doc:
                self.logger.warning(f"Order not found: {order_id}")
                return False
            
            # Check if order is already processed or cancelled
            if order_doc.get("status") in ["COMPLETED", "CANCELLED"]:
                self.logger.warning(f"Order already processed or cancelled: {order_id}")
                return False
            
            order_type = order_doc.get("order_type")
            is_subscription = order_doc.get("is_subscription", False)
            
            # Handle subscription cancellation
            if is_subscription and order_type in ["subscription_purchase", "subscription_upgrade"]:
                return await self._cancel_subscription_order(order_doc, user_id)
            else:
                return False

        except Exception as e:
            self.logger.error(f"Exception cancelling PayPal order: {str(e)}")
            raise

    async def _cancel_subscription_order(self, order_doc: dict, user_id: str) -> bool:
        """Cancel subscription order and PayPal subscription"""
        try:
            # Get PayPal subscription ID from order metadata or capture response
            subscription_id = None
            
            if order_doc and "order_id" in order_doc:
                subscription_id = order_doc["order_id"]
            
            success = True
            
            # Cancel PayPal subscription if subscription ID exists
            if subscription_id:
                success = await self._cancel_paypal_subscription(subscription_id)
            
                # Cancel subscription in our system using UserPlanManager
                if success:
                    try:
                        user_plan_manager = UserPlanManager()
                        cancel_result = await user_plan_manager.cancel_subscription(
                            user_id, 
                            subscription_id,
                            "User requested cancellation"

                        )
                        
                        if not cancel_result.success:
                            self.logger.warning(f"Failed to cancel subscription in system: {cancel_result.message}")
                            # Still mark order as cancelled even if system cancellation fails
                            
                    except Exception as e:
                        self.logger.error(f"Failed to cancel subscription in system: {str(e)}")
                        # Continue with order cancellation
                
                    self.logger.info(f"Subscription order cancelled successfully: {order_doc['order_id']}")
                    return True
                else:
                    self.logger.warning(f"Failed to cancel subscription paypal order: {order_doc['order_id']}")
                    return False

            return False
        except Exception as e:
            self.logger.error(f"Failed to cancel subscription order: {str(e)}")
            return False

    async def _cancel_regular_order(self, order_id: str, user_id: str) -> bool:
        """Cancel regular (non-subscription) PayPal order"""
        try:
            # For regular orders, just mark as cancelled in database
            # PayPal API doesn't directly support order cancellation for completed orders
            orders_collection = await self._get_orders_collection()
            result = await orders_collection.update_one(
                {"order_id": order_id, "user_id": user_id},
                {
                    "$set": {
                        "status": "CANCELLED",
                        "updated_at": datetime.now(),
                        "cancelled_by_user": True
                    }
                }
            )
            
            if result.modified_count > 0:
                self.logger.info(f"Regular PayPal order cancelled successfully: {order_id}")
                return True
            else:
                self.logger.warning(f"Failed to cancel regular PayPal order, order not found: {order_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"Exception cancelling regular PayPal order: {str(e)}")
            return False

    async def _cancel_paypal_subscription(self, subscription_id: str) -> bool:
        """Cancel PayPal subscription"""
        try:
            access_token = await self.get_access_token()
            
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}'
            }
            
            # Cancel subscription with reason
            cancel_data = {
                "reason": "User requested cancellation"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/v1/billing/subscriptions/{subscription_id}/cancel",
                    headers=headers,
                    json=cancel_data
                ) as response:
                    if response.status == 204:
                        self.logger.info(f"PayPal subscription cancelled successfully: {subscription_id}")
                        return True
                    elif response.status == 404:
                        # Subscription not found - it might already be cancelled or never existed
                        error_text = await response.text()
                        self.logger.warning(f"PayPal subscription not found (already cancelled or invalid): {subscription_id} - {error_text}")
                        # Return True since the goal (subscription not active) is achieved
                        return True
                    else:
                        error_text = await response.text()
                        self.logger.error(f"Failed to cancel PayPal subscription: {response.status} - {error_text}")
                        return False
                        
        except Exception as e:
            self.logger.error(f"Exception cancelling PayPal subscription: {str(e)}")
            return False

    async def _get_subscription_id_from_order(self, order_id: str) -> Optional[str]:
        """Get PayPal subscription ID associated with an order"""
        try:
            # This is a placeholder - you might need to store subscription IDs 
            # when creating subscriptions or retrieve them from PayPal
            # For now, we'll check if there's a subscription_id stored in the order
            orders_collection = await self._get_orders_collection()
            order_doc = await orders_collection.find_one({"order_id": order_id})
            
            if order_doc:
                # Check various places where subscription ID might be stored
                subscription_id = (
                    order_doc.get("subscription_id") or
                    order_doc.get("paypal_subscription_id") or
                    (order_doc.get("capture_response", {}).get("subscription_id")) or
                    (order_doc.get("metadata", {}).get("subscription_id"))
                )
                
                return subscription_id
            
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to get subscription ID from order: {str(e)}")
            return None

    async def get_user_orders(self, user_id: str, limit: int = 10, skip: int = 0) -> list:
        """Get user's PayPal order history"""
        try:
            orders_collection = await self._get_orders_collection()
            cursor = orders_collection.find(
                {"user_id": user_id}
            ).sort("created_at", -1).skip(skip).limit(limit)
            
            orders = await cursor.to_list(length=limit)
            
            # Convert ObjectId to string
            for order in orders:
                order["_id"] = str(order["_id"])
            
            return orders
            
        except Exception as e:
            self.logger.error(f"Exception getting user PayPal order history: {str(e)}")
            raise

    async def send_invoice_for_order(self, order_id: str, user_id: str, invoice_number: Optional[str] = None) -> Dict[str, Any]:
        """根据订单ID创建并发送发票（修改：不再调用PayPal发送接口，改为后端邮件发送已支付发票）"""
        try:
            self.logger.info(f"Creating invoice for order {order_id} for user {user_id}")
            
            # 查找订单
            orders_collection = await self._get_orders_collection()
            order_doc = await orders_collection.find_one({
                "order_id": order_id,
                "user_id": user_id
            })
            
            if not order_doc:
                self.logger.error(f"Order not found: {order_id} for user {user_id}")
                raise Exception("Order not found or access denied")
            
            # 检查订单状态
            if order_doc.get("status") not in ["COMPLETED", "APPROVED"]:
                self.logger.error(f"Order not in valid state: {order_id}, status: {order_doc.get('status')}")
                raise Exception("Invoice can only be created for completed or approved orders")
            
            # 获取用户信息
            user_info = await self._get_user_info(user_id)
            if not user_info:
                self.logger.error(f"User information not found for user: {user_id}")
                raise Exception("User information not found")
            
            self.logger.info(f"Step 1: Getting PayPal access token")
            # 获取PayPal访问令牌
            access_token = await self.get_access_token()
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}",
                "PayPal-Request-Id": str(uuid.uuid4()),
                "Prefer": "return=representation"
            }
            
            self.logger.info(f"Step 2: Building invoice data for order {order_id}")
            # 构建发票数据（支持自定义发票号覆盖）
            invoice_data = await self._build_invoice_data_for_order(order_doc, user_info, invoice_number_override=invoice_number)
            self.logger.info(f"Invoice data built successfully. Invoice number: {invoice_data['detail']['invoice_number']}")
            
            # 创建发票
            async with aiohttp.ClientSession() as session:
                # 1. 创建发票草稿
                create_url = f"{self.base_url}/v2/invoicing/invoices"
                self.logger.info(f"Step 3: Creating invoice draft at {create_url}")
                
                async with session.post(create_url, headers=headers, json=invoice_data) as response:
                    response_text = await response.text()
                    self.logger.info(f"PayPal create invoice response: {response}")
                    
                    if response.status != 201:
                        self.logger.error(f"Failed to create order invoice: Status {response.status}, Response: {response_text}")
                        raise Exception(f"Failed to create invoice: PayPal API returned status {response.status}")
                    
                    # 优先尝试从JSON获取id，其次从Location或href/links解析
                    invoice_id = None
                    invoice_response = {}
                    try:
                        invoice_response = await response.json()
                    except Exception as json_error:
                        self.logger.warning(f"Failed to parse JSON response for invoice creation, will fallback to headers/links: {json_error}")
                    
                    if isinstance(invoice_response, dict):
                        invoice_id = invoice_response.get("id")
                        if not invoice_id:
                            # 尝试 href 字段
                            href = invoice_response.get("href")
                            if href and "/invoicing/invoices/" in href:
                                invoice_id = href.rsplit("/", 1)[-1]
                            else:
                                # 尝试 links[self]
                                links = invoice_response.get("links", [])
                                for link in links:
                                    if link.get("rel") == "self" and link.get("href"):
                                        href = link["href"]
                                        if "/invoicing/invoices/" in href:
                                            invoice_id = href.rsplit("/", 1)[-1]
                                            break
                    if not invoice_id:
                        # 回退到 Location 头
                        location = response.headers.get("Location")
                        if location and "/invoicing/invoices/" in location:
                            invoice_id = location.rsplit("/", 1)[-1]
                    
                    if not invoice_id:
                        self.logger.error(f"Invoice ID not returned from PayPal. Response: {invoice_response}, Location: {response.headers.get('Location')}")
                        raise Exception("Invoice ID not returned from PayPal")
                    
                self.logger.info(f"Step 4: Invoice created successfully with ID: {invoice_id}")
                
                # 4.1 记录付款，标记发票为已支付（PAID）
                record_payment_url = f"{self.base_url}/v2/invoicing/invoices/{invoice_id}/payments"
                
                # 从 capture_response 中提取支付信息
                capture_response = order_doc.get("capture_response", {})
                purchase_units = capture_response.get("purchase_units", [])
                
                if purchase_units and len(purchase_units) > 0:
                    captures = purchase_units[0].get("payments", {}).get("captures", [])
                    if captures and len(captures) > 0:
                        capture_id = captures[0].get("id")
                        amount_info = captures[0].get("amount", {})
                        currency = amount_info.get("currency_code", "USD")
                        amount = amount_info.get("value", str(order_doc.get("amount", 0)))
                    else:
                        # 兜底：使用订单中的金额信息
                        capture_id = None
                        amount = str(order_doc.get("amount", 0))
                        currency = order_doc.get("currency", "USD")
                else:
                    # 兜底：使用订单中的金额信息
                    capture_id = None
                    amount = str(order_doc.get("amount", 0))
                    currency = order_doc.get("currency", "USD")
                
                # 统一金额为两位小数的字符串
                amount_value = amount if isinstance(amount, str) else f"{float(amount):.2f}"
                try:
                    # 如果是字符串但不是两位小数，规范化
                    amount_value = f"{float(amount_value):.2f}"
                except Exception:
                    # 若解析失败，保留原值作为兜底
                    pass

                payment_payload = {
                    "method": "PAYPAL",
                    "amount": {
                        "currency_code": currency,
                        "value": amount_value
                    },
                    "payment_date": datetime.utcnow().strftime("%Y-%m-%d"),
                    "note": f"Order {order_id} paid via PayPal"
                }
                
                # 如果有capture_id，添加到note中
                if capture_id:
                    payment_payload["note"] = f"Order {order_id} paid via PayPal (Capture ID: {capture_id})"

                self.logger.info(f"Step 4.1: Recording payment for invoice {invoice_id} at {record_payment_url}")
                async with session.post(record_payment_url, headers=headers, json=payment_payload) as rp_response:
                    rp_text = await rp_response.text()
                    self.logger.info(f"PayPal record-payment response: Status {rp_response.status}, Content: {rp_text}")
                    if rp_response.status not in {200, 201}:
                        self.logger.error(f"Failed to record payment for invoice {invoice_id}: Status {rp_response.status}, Response: {rp_text}")
                        raise Exception(f"Failed to mark invoice as paid: PayPal API returned status {rp_response.status}")
                
                # 修改流程：不调用 PayPal 发送接口，改为后端邮件发送已支付发票
                try:
                    subject = "Your paid invoice from AlignSpires"
                    payment_date = datetime.utcnow().strftime("%Y-%m-%d")
                    # amount_value 为字符串，转换为 float 以满足 HTML 生成器签名
                    try:
                        amount_value_float = float(amount_value)
                    except Exception:
                        amount_value_float = float(order_doc.get("amount", 0))
                    email_body = self._build_paid_invoice_email_html(
                        invoice_response, user_info, amount_value_float, currency, payment_date
                    )
                    recipient_email = user_info.get("email", "")
                    if not recipient_email:
                        # 备选：从发票 JSON 中取收件人邮箱
                        primary_recipients = invoice_response.get("primary_recipients", []) or []
                        recipient_email = (
                            primary_recipients[0].get("billing_info", {}).get("email_address", "")
                            if primary_recipients else ""
                        )
                    if recipient_email:
                        sent = await self._send_email_placeholder(recipient_email, subject, email_body)
                        if sent:
                            self.logger.info(f"Paid invoice email sent to {recipient_email} for invoice {invoice_id}")
                        else:
                            self.logger.error(f"Failed to send paid invoice email to {recipient_email} for invoice {invoice_id}")
                    else:
                        self.logger.warning(f"No recipient email available for invoice {invoice_id}, skip sending.")
                except Exception as e:
                    self.logger.error(f"Error when emailing paid invoice for {invoice_id}: {str(e)}")
                
                # 更新数据库（记录 invoice_id 与发送时间，无需保存 PayPal 发票链接）
                orders_collection = await self._get_orders_collection()
                await orders_collection.update_one(
                    {"order_id": order_id, "user_id": user_id},
                    {
                        "$set": {
                            "invoice_id": invoice_id,
                            "invoice_sent_at": datetime.utcnow(),
                            "invoice_url": None,
                            "payer_view_url": None
                        }
                    }
                )
                
                # 结束流程（不调用 PayPal send 接口）
                return {
                    "success": True,
                    "invoice_id": invoice_id,
                    "status": "PAID_EMAIL_SENT",
                    "message": "Paid invoice email sent",
                    "invoice_url": None
                }
                        
        except Exception as e:
            self.logger.error(f"Exception in send_invoice_for_order: {str(e)}", exc_info=True)
            # 重新抛出异常，让上层处理HTTP状态码
            raise e

    async def send_invoice_for_subscription(self, subscription_id: str, user_id: str, invoice_number: Optional[str] = None) -> Dict[str, Any]:
        """根据订阅ID创建并发送发票（修改：不再调用PayPal发送接口，改为后端邮件发送已支付发票）"""
        try:
            self.logger.info(f"Creating invoice for subscription {subscription_id} for user {user_id}")
            
            # 查找包含该订阅ID的订单
            orders_collection = await self._get_orders_collection()
            order_doc = await orders_collection.find_one({
                "order_id": subscription_id,
                "user_id": user_id
            })
            self.logger.info(f"Creating invoice for order {order_doc}")
            
            if not order_doc:
                self.logger.error(f"Subscription order not found: {subscription_id} for user {user_id}")
                raise Exception("Subscription order not found or access denied")
            
            # 检查订阅状态
            if order_doc.get("status") != "ACTIVE":
                self.logger.error(f"Subscription not active: {subscription_id}, status: {order_doc.get('status')}")
                raise Exception("Invoice can only be created for active subscriptions")
            
            # 获取用户信息
            user_info = await self._get_user_info(user_id)
            if not user_info:
                self.logger.error(f"User information not found for user: {user_id}")
                raise Exception("User information not found")
            
            self.logger.info(f"Step 1: Getting PayPal access token")
            # 获取PayPal访问令牌
            access_token = await self.get_access_token()
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}",
                "PayPal-Request-Id": str(uuid.uuid4()),
                "Prefer": "return=representation"
            }
            
            self.logger.info(f"Step 2: Building invoice data for subscription {subscription_id}")
            # 构建发票数据
            invoice_data = await self._build_invoice_data_for_subscription(order_doc, user_info, subscription_id, invoice_number)
            self.logger.info(f"Invoice data built successfully. Invoice number: {invoice_data['detail']['invoice_number']}")
            
            # 创建发票
            async with aiohttp.ClientSession() as session:
                # 1. 创建发票草稿
                create_url = f"{self.base_url}/v2/invoicing/invoices"
                self.logger.info(f"Step 3: Creating invoice draft at {create_url}")
                
                async with session.post(create_url, headers=headers, json=invoice_data) as response:
                    response_text = await response.text()
                    self.logger.info(f"PayPal create invoice response: Status {response.status}, Content: {response_text}")
                    
                    if response.status != 201:
                        self.logger.error(f"Failed to create subscription invoice: Status {response.status}, Response: {response_text}")
                        raise Exception(f"Failed to create invoice: PayPal API returned status {response.status}")
                    
                    # 优先尝试从JSON获取id，其次从Location或href/links解析
                    invoice_id = None
                    invoice_response = {}
                    try:
                        invoice_response = await response.json()
                    except Exception as json_error:
                        self.logger.warning(f"Failed to parse JSON response for invoice creation, will fallback to headers/links: {json_error}")
                    
                    if isinstance(invoice_response, dict):
                        invoice_id = invoice_response.get("id")
                        if not invoice_id:
                            href = invoice_response.get("href")
                            if href and "/invoicing/invoices/" in href:
                                invoice_id = href.rsplit("/", 1)[-1]
                            else:
                                links = invoice_response.get("links", [])
                                for link in links:
                                    if link.get("rel") == "self" and link.get("href"):
                                        href = link["href"]
                                        if "/invoicing/invoices/" in href:
                                            invoice_id = href.rsplit("/", 1)[-1]
                                            break
                    if not invoice_id:
                        location = response.headers.get("Location")
                        if location and "/invoicing/invoices/" in location:
                            invoice_id = location.rsplit("/", 1)[-1]
                    
                    if not invoice_id:
                        self.logger.error(f"Invoice ID not returned from PayPal. Response: {invoice_response}, Location: {response.headers.get('Location')}")
                        raise Exception("Invoice ID not returned from PayPal")
                
                self.logger.info(f"Step 4: Invoice created successfully with ID: {invoice_id}")
                
                # 4.1 记录付款，标记发票为已支付（PAID）
                record_payment_url = f"{self.base_url}/v2/invoicing/invoices/{invoice_id}/payments"
                amount = float(order_doc.get("amount", 0))
                currency = order_doc.get("currency", "USD")
                amount_value = f"{amount:.2f}"

                payment_payload = {
                    "method": "PAYPAL",
                    "amount": {
                        "currency_code": currency,
                        "value": amount_value
                    },
                    "payment_date": datetime.utcnow().strftime("%Y-%m-%d"),
                    "note": f"Subscription {subscription_id} paid via PayPal"
                }

                self.logger.info(f"Step 4.1: Recording payment for invoice {invoice_id} at {record_payment_url}")
                async with session.post(record_payment_url, headers=headers, json=payment_payload) as rp_response:
                    rp_text = await rp_response.text()
                    self.logger.info(f"PayPal record-payment response: Status {rp_response.status}, Content: {rp_text}")
                    if rp_response.status not in {200, 201}:
                        self.logger.error(f"Failed to record payment for invoice {invoice_id}: Status {rp_response.status}, Response: {rp_text}")
                        raise Exception(f"Failed to mark invoice as paid: PayPal API returned status {rp_response.status}")
                
                # 修改流程：不调用 PayPal 发送接口，改为后端邮件发送已支付发票
                try:
                    subject = "Your paid invoice from AlignSpires"
                    payment_date = datetime.utcnow().strftime("%Y-%m-%d")
                    # amount_value 为字符串，转换为 float 以满足 HTML 生成器签名
                    try:
                        amount_value_float = float(amount_value)
                    except Exception:
                        amount_value_float = amount
                    email_body = self._build_paid_invoice_email_html(
                        invoice_response, user_info, amount_value_float, currency, payment_date
                    )
                    recipient_email = user_info.get("email", "")
                    if not recipient_email:
                        # 备选：从发票 JSON 中取收件人邮箱
                        primary_recipients = invoice_response.get("primary_recipients", []) or []
                        recipient_email = (
                            primary_recipients[0].get("billing_info", {}).get("email_address", "")
                            if primary_recipients else ""
                        )
                    if recipient_email:
                        sent = await self._send_email_placeholder(recipient_email, subject, email_body)
                        if sent:
                            self.logger.info(f"Paid invoice email sent to {recipient_email} for invoice {invoice_id}")
                        else:
                            self.logger.error(f"Failed to send paid invoice email to {recipient_email} for invoice {invoice_id}")
                    else:
                        self.logger.warning(f"No recipient email available for invoice {invoice_id}, skip sending.")
                except Exception as e:
                    self.logger.error(f"Error when emailing paid invoice for {invoice_id}: {str(e)}")
                
                # 更新数据库（记录 invoice_id 与发送时间，无需保存 PayPal 发票链接）
                orders_collection = await self._get_orders_collection()
                await orders_collection.update_one(
                    {"order_id": subscription_id, "user_id": user_id},
                    {
                        "$set": {
                            "invoice_id": invoice_id,
                            "invoice_sent_at": datetime.utcnow(),
                            "invoice_url": None,
                            "payer_view_url": None
                        }
                    }
                )
                
                # 结束流程（不调用 PayPal send 接口）
                return {
                    "success": True,
                    "invoice_id": invoice_id,
                    "status": "PAID_EMAIL_SENT",
                    "message": "Paid invoice email sent",
                    "invoice_url": None
                }
                        
        except Exception as e:
            self.logger.error(f"Exception in send_invoice_for_subscription: {str(e)}", exc_info=True)
            # 重新抛出异常，让上层处理HTTP状态码
            raise e

    async def _build_invoice_data_for_order(self, order_doc: dict, user_info: dict, invoice_number_override: Optional[str] = None) -> dict:
        """构建订单发票数据，支持自定义覆盖发票号（长度≤25）"""
        # 获取订单详情
        amount = float(order_doc.get("amount", 0))
        currency = order_doc.get("currency", "USD")
        
        # 商品展示名称与描述（使用商品简介，不再使用付款日期）
        display_name = "Payment"
        display_desc = "One-time purchase"
        plan_config_data = order_doc.get("plan_config_data", {}) or {}
        
        if order_doc.get("is_subscription"):
            plan_type = order_doc.get("subscription_plan_type", "")
            plan_desc = plan_config_data.get("paypal_plan_description") or plan_config_data.get("description") or (f"{plan_type} subscription plan" if plan_type else "Subscription plan")
            display_name = plan_config_data.get("paypal_plan_name") or (f"Subscription Plan: {plan_type}" if plan_type else "Subscription Plan")
            display_desc = plan_desc
        elif order_doc.get("data_addon_type"):
            addon_type = order_doc.get("data_addon_type", "")
            credits_val = plan_config_data.get("credits")
            if credits_val:
                display_name = f"{credits_val} credits"
            else:
                import re
                m = re.search(r"(\d+)", str(addon_type))
                display_name = f"{m.group(1)} credits" if m else str(addon_type).replace("_", " ").title()
            display_desc = plan_config_data.get("paypal_product_description") or plan_config_data.get("description") or f"{display_name} add-on"
        
        # 生成或使用自定义发票号（限制25字符）
        if invoice_number_override and invoice_number_override.strip():
            custom = invoice_number_override.strip()
            if len(custom) > 25:
                raise Exception("Invoice number exceeds 25 characters")
            invoice_number = custom
        else:
            order_id = order_doc.get('order_id', '')[:8]  # 取前8位
            timestamp = str(int(datetime.utcnow().timestamp()))[-6:]  # 取时间戳后6位
            invoice_number = f"INV-{order_id}-{timestamp}"  # 格式: INV-12345678-123456 (最多21字符)
        
        invoice_data = {
            "detail": {
                "invoice_number": invoice_number,
                "reference": f"Order: {order_doc.get('order_id', '')}",
                "invoice_date": datetime.utcnow().strftime("%Y-%m-%d"),
                "currency_code": currency,
                "note": f"Invoice for order {order_doc.get('order_id', '')}",
            },
            "primary_recipients": [
                {
                    "billing_info": {
                        "name": {
                            "given_name": user_info.get("first_name", ""),
                            "surname": user_info.get("last_name", "")
                        },
                        "email_address": user_info.get("email", "")
                    }
                }
            ],
            "items": [
                {
                    "name": display_name,
                    "description": display_desc,
                    "quantity": "1",
                    "unit_amount": {
                        "currency_code": currency,
                        "value": str(amount)
                    }
                }
            ],
            "configuration": {
                "partial_payment": {
                    "allow_partial_payment": False
                },
                "allow_tip": False,
                "tax_calculated_after_discount": True,
                "tax_inclusive": False
            }
        }
        
        return invoice_data

    async def _build_invoice_data_for_subscription(self, order_doc: dict, user_info: dict, subscription_id: str, invoice_number_override: Optional[str] = None) -> dict:
        """构建订阅发票数据"""
        # 获取订单详情
        amount = float(order_doc.get("amount", 0))
        currency = order_doc.get("currency", "USD")
        plan_type = order_doc.get("subscription_plan_type", "")

        # 从 SUBSCRIPTION_PLANS_CONFIG 中获取计划简介
        plan_config = None
        try:
            if plan_type:
                plan_config = SUBSCRIPTION_PLANS_CONFIG.get(ConfigSubscriptionPlanType(plan_type))
        except Exception:
            plan_config = None
        plan_details = (plan_config or {}).get("plan_details")
        plan_desc = (plan_config or {}).get("paypal_plan_description") or (getattr(plan_details, "description", "") if plan_details else "")

        # 生成或使用自定义发票号（限制25字符）
        if invoice_number_override and invoice_number_override.strip():
            custom = invoice_number_override.strip()
            if len(custom) > 25:
                raise Exception("Invoice number exceeds 25 characters")
            invoice_number = custom
        else:
            sub_id = subscription_id[:8]
            timestamp = str(int(datetime.utcnow().timestamp()))[-6:]
            invoice_number = f"INV-S-{sub_id}-{timestamp}"

        invoice_data = {
            "detail": {
                "invoice_number": invoice_number,
                "reference": f"Subscription: {subscription_id}",
                "invoice_date": datetime.utcnow().strftime("%Y-%m-%d"),
                "currency_code": currency,
                "note": f"Invoice for subscription {subscription_id}",
            },
            "primary_recipients": [
                {
                    "billing_info": {
                        "name": {
                            "given_name": user_info.get("first_name", ""),
                            "surname": user_info.get("last_name", "")
                        },
                        "email_address": user_info.get("email", "")
                    }
                }
            ],
            "items": [
                {
                    "name": f"Subscription Plan: {plan_type}" if plan_type else "Subscription Plan",
                    "description": plan_desc or (f"{plan_type} subscription plan" if plan_type else "Subscription plan"),
                    "quantity": "1",
                    "unit_amount": {
                        "currency_code": currency,
                        "value": str(amount)
                    }
                }
            ],
            "configuration": {
                "partial_payment": {
                    "allow_partial_payment": False
                },
                "allow_tip": False,
                "tax_calculated_after_discount": True,
                "tax_inclusive": False
            }
        }
        return invoice_data

    def _build_paid_invoice_email_html(self, invoice_json: dict, user_info: dict, amount_value: float, currency_code: str, payment_date: str) -> str:
        # 组装发票基础信息（更健壮的取值与回退）
        detail = invoice_json.get('detail', {}) or {}
        invoice_id = invoice_json.get('id', '') or ''
        invoice_number = detail.get('invoice_number') or invoice_id
        invoice_date = detail.get('invoice_date') or payment_date or ''
        
        # 收件人信息（不再在页眉展示）
        primary_recipients = invoice_json.get('primary_recipients', []) or []
        recipient_billing_info = (primary_recipients[0].get('billing_info', {}) if primary_recipients else {}) or {}
        recipient_name = recipient_billing_info.get('name', {}) or {}
        recipient_full_name = recipient_name.get('full_name') or f"{recipient_name.get('given_name', '')} {recipient_name.get('surname', '')}".strip()
        recipient_email = recipient_billing_info.get('email_address') or user_info.get('email', '') or ''
        
        # 项目与金额
        items = invoice_json.get('items', []) or []
        amount = invoice_json.get('amount', {}) or {}
        breakdown = amount.get('breakdown', {}) or {}
        item_total = breakdown.get('item_total', {}) or {}
        tax_total = breakdown.get('tax_total', {}) or {}
        discount = breakdown.get('discount', {}) or {}
        invoice_discount = (discount.get('invoice_discount') or {}).get('amount', {}) or {}
        
        amount_currency = amount.get('currency_code') or currency_code or 'USD'
        status_label = 'PAID'
        payment_method_label = 'PayPal'
        
        # 构造项目明细 HTML（增加行合计，单位价格使用每项的币种）
        from decimal import Decimal, InvalidOperation
        
        def to_decimal(v, default='0.00'):
            try:
                return Decimal(str(v))
            except (InvalidOperation, TypeError, ValueError):
                return Decimal(default)
        
        items_html_rows = ''
        if items:
            for it in items:
                name = it.get('name', '') or ''
                desc = it.get('description', '') or ''
                qty = to_decimal(it.get('quantity', '1'), default='1')
                unit_amount_obj = it.get('unit_amount', {}) or {}
                unit_currency = unit_amount_obj.get('currency_code') or amount_currency
                unit_value = to_decimal(unit_amount_obj.get('value', '0.00'), default='0.00')
                line_total = qty * unit_value
                items_html_rows += f"""
                <tr>
                    <td style='padding:10px;border-bottom:1px solid #eee;'>{name}</td>
                    <td style='padding:10px;border-bottom:1px solid #eee;color:#6b7280;'>{desc}</td>
                    <td style='padding:10px;border-bottom:1px solid #eee;text-align:center;'>{qty.normalize()}</td>
                    <td style='padding:10px;border-bottom:1px solid #eee;text-align:right;'>{unit_currency} {unit_value:.2f}</td>
                    <td style='padding:10px;border-bottom:1px solid #eee;text-align:right;font-weight:600;'>{unit_currency} {line_total:.2f}</td>
                </tr>
            """
        else:
            items_html_rows = """
            <tr>
                <td colspan='5' style='padding:12px;border-bottom:1px solid #eee;text-align:center;color:#888;'>No items</td>
            </tr>
        """
        
        item_total_value = item_total.get('value', f'{amount_value:.2f}')
        tax_total_value = tax_total.get('value', '0.00')
        discount_value = invoice_discount.get('value', '0.00')
        grand_total_value = amount.get('value', f'{amount_value:.2f}')
        
        body = f'''
    <div style="font-family: Inter, Arial, sans-serif; color:#222; line-height:1.6;">
      <div style="max-width:720px; margin:0 auto; padding:24px; border:1px solid #e5e7eb; border-radius:12px;">
        <div style="display:flex; justify-content:space-between; align-items:flex-end;">
          <div>
            <h2 style="margin:0; font-size:22px; letter-spacing:0.2px;">Invoice</h2>
            <p style="margin:4px 0 0; color:#6b7280; font-size:13px;">Date: {invoice_date}</p>
          </div>
          <div>
            <span style="display:inline-block; padding:6px 10px; border-radius:20px; background:#e6f4ea; color:#0b8043; font-weight:600; font-size:12px;">{status_label}</span>
            <span style="margin-left:8px; color:#6b7280; font-size:12px;">#{invoice_number}</span>
          </div>
        </div>

        <table style="width:100%; border-collapse:collapse; margin-top:16px;">
          <thead>
            <tr style="background:#f9fafb;">
              <th style="text-align:left; padding:10px; border-bottom:2px solid #e5e7eb; font-weight:600;">Item</th>
              <th style="text-align:left; padding:10px; border-bottom:2px solid #e5e7eb; font-weight:600;">Description</th>
              <th style="text-align:center; padding:10px; border-bottom:2px solid #e5e7eb; font-weight:600;">Qty</th>
              <th style="text-align:right; padding:10px; border-bottom:2px solid #e5e7eb; font-weight:600;">Unit Price</th>
              <th style="text-align:right; padding:10px; border-bottom:2px solid #e5e7eb; font-weight:600;">Line Total</th>
            </tr>
          </thead>
          <tbody>
            {items_html_rows}
          </tbody>
        </table>

        <div style="margin-top:16px; display:flex; justify-content:flex-end;">
          <div style="min-width:240px;">
            <div style="display:flex; justify-content:space-between; margin:2px 0;">
              <span style="color:#6b7280;">Subtotal</span>
              <span style="font-weight:600;">{amount_currency} {item_total_value}</span>
            </div>
            <div style="display:flex; justify-content:space-between; margin:2px 0;">
              <span style="color:#6b7280;">Tax</span>
              <span style="font-weight:600;">{amount_currency} {tax_total_value}</span>
            </div>
            <div style="display:flex; justify-content:space-between; margin:2px 0;">
              <span style="color:#6b7280;">Discount</span>
              <span style="font-weight:600;">{amount_currency} {discount_value}</span>
            </div>
            <div style="display:flex; justify-content:space-between; margin:8px 0; font-size:16px;">
              <span>Total</span>
              <span style="font-weight:700;">{amount_currency} {grand_total_value}</span>
            </div>
          </div>
        </div>

        <div style="margin-top:12px; display:flex; justify-content:space-between;">
          <p style="margin:0; color:#374151;">
            <span style="color:#6b7280;">Payment method</span>
            <span style="font-weight:600; margin-left:6px;">{payment_method_label}</span>
          </p>
          <p style="margin:0; color:#374151; text-align:right;">
            <span style="color:#6b7280;">Payment date</span>
            <span style="font-weight:600; margin-left:6px;">{payment_date}</span>
          </p>
        </div>

        <div style="margin-top:12px; color:#6b7280; font-size:12px;">
          <p style="margin:0;">Invoice ID: {invoice_id}</p>
        </div>

        <hr style="margin:18px 0; border:0; border-top:1px solid #e5e7eb;">
        <p style="margin:0; color:#374151;">Thank you for your purchase!</p>
        <p style="margin:2px 0 0; color:#6b7280;">- AlignSpires Team</p>
      </div>
    </div>
    '''
        return body

    def _get_plan_data_from_config(self, order_request: PayPalOrderRequest) -> Optional[Dict[str, Any]]:
        """从 config_user_plan.py 中获取计划数据"""
        try:
            self.logger.info(f"Getting plan data from config for order: subscription={order_request.is_subscription}, "
                           f"plan_type={order_request.subscription_plan_type}, addon_type={order_request.data_addon_type}")
            
            # 判断是订阅计划还是数据附加项
            if order_request.is_subscription and order_request.subscription_plan_type:
                # 处理订阅计划
                try:
                    # 将字符串转换为枚举类型
                    plan_type = ConfigSubscriptionPlanType(order_request.subscription_plan_type)
                    plan_config = SUBSCRIPTION_PLANS_CONFIG.get(plan_type)
                    
                    if plan_config:
                        plan_details = plan_config["plan_details"]
                        result = {
                            "type": "subscription",
                            "price": plan_details.price,
                            "currency": plan_details.currency,
                            "description": plan_details.description,
                            "paypal_plan_name": plan_config.get("paypal_plan_name", f"AlignSpires {plan_type.value.title()} Plan"),
                            "paypal_plan_description": plan_config.get("paypal_plan_description", plan_details.description),
                            "paypal_product_category": plan_config.get("paypal_product_category", "SOFTWARE"),
                            "billing_frequency": plan_config.get("billing_frequency", {"interval_unit": "MONTH", "interval_count": 1}),
                            "trial_period_days": plan_config.get("trial_period_days", 0),
                            "setup_fee": 0
                        }
                        self.logger.info(f"Found subscription plan config: {result}")
                        return result
                except ValueError:
                    self.logger.warning(f"Invalid subscription plan type: {order_request.subscription_plan_type}")
                    
            elif not order_request.is_subscription and order_request.data_addon_type:
                # 处理数据附加项
                try:
                    # 将字符串转换为枚举类型
                    addon_type = ConfigDataAddonType(order_request.data_addon_type)
                    addon_config = DATA_ADDONS_CONFIG.get(addon_type)
                    
                    if addon_config:
                        addon_details = addon_config["addon_details"]
                        result = {
                            "type": "addon",
                            "price": addon_details.price,
                            "currency": addon_details.currency,
                            "description": addon_details.description,
                            "paypal_product_name": addon_config.get("paypal_product_name", f"AlignSpires {addon_details.credits} Credits Add-on"),
                            "paypal_product_description": addon_config.get("paypal_product_description", addon_details.description),
                            "paypal_product_category": addon_config.get("paypal_product_category", "DIGITAL_GOODS"),
                            "credits": addon_details.credits,
                            "validity_days": addon_config.get("validity_days", 90)
                        }
                        self.logger.info(f"Found addon config: {result}")
                        return result
                except ValueError:
                    self.logger.warning(f"Invalid data addon type: {order_request.data_addon_type}")
            
            # 如果没有找到配置，返回None
            self.logger.warning(f"No configuration found for order request: subscription={order_request.is_subscription}, "
                              f"plan_type={order_request.subscription_plan_type}, addon_type={order_request.data_addon_type}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting plan data from config: {str(e)}")
