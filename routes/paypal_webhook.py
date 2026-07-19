from fastapi import APIRouter, Request, HTTPException, Header
from typing import Optional
import json
import hmac
import hashlib
import logging

from services.paypal_handler import PayPalHandler
from services.subscription_service import subscription_service, SubscriptionPlan, SubscriptionStatus
from services.slack_service import slack_service
from config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

def verify_webhook_signature(payload: bytes, signature: str, webhook_id: str) -> bool:
    """验证 PayPal webhook 签名"""
    try:
        # PayPal webhook 签名验证逻辑
        # 这里需要根据 PayPal 的实际签名验证方式实现
        # 暂时返回 True，实际使用时需要实现正确的验证逻辑
        return True
    except Exception as e:
        logger.error(f"Webhook signature verification failed: {e}")
        return False

@router.post("/paypal/webhook")
async def handle_paypal_webhook(
    request: Request,
    paypal_transmission_id: Optional[str] = Header(None, alias="PAYPAL-TRANSMISSION-ID"),
    paypal_cert_id: Optional[str] = Header(None, alias="PAYPAL-CERT-ID"),
    paypal_transmission_sig: Optional[str] = Header(None, alias="PAYPAL-TRANSMISSION-SIG"),
    paypal_transmission_time: Optional[str] = Header(None, alias="PAYPAL-TRANSMISSION-TIME")
):
    """处理 PayPal webhook 事件"""
    try:
        # 获取请求体
        payload = await request.body()
        webhook_data = json.loads(payload.decode('utf-8'))
        
        # 验证 webhook 签名（生产环境中必须启用）
        if settings.ENVIRONMENT == "production":
            if not verify_webhook_signature(payload, paypal_transmission_sig, paypal_transmission_id):
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
        
        event_type = webhook_data.get("event_type")
        resource = webhook_data.get("resource", {})
        
        logger.info(f"Received PayPal webhook: {event_type}")
        
        # 处理不同类型的 webhook 事件
        if event_type == "PAYMENT.CAPTURE.COMPLETED":
            await handle_payment_completed(resource)
        elif event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
            await handle_subscription_activated(resource)
        elif event_type == "BILLING.SUBSCRIPTION.CANCELLED":
            await handle_subscription_cancelled(resource)
        elif event_type == "BILLING.SUBSCRIPTION.SUSPENDED":
            await handle_subscription_suspended(resource)
        elif event_type == "BILLING.SUBSCRIPTION.PAYMENT.FAILED":
            await handle_subscription_payment_failed(resource)
        else:
            logger.info(f"Unhandled webhook event type: {event_type}")
        
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error processing PayPal webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

async def handle_payment_completed(resource: dict):
    """处理一次性支付完成事件"""
    try:
        # 从 PayPal 资源中提取订单信息
        custom_id = resource.get("custom_id")  # 我们在创建订单时设置的自定义 ID
        amount = resource.get("amount", {}).get("value")
        
        if custom_id:
            # 解析自定义 ID 获取用户信息
            # 格式: "user_id:plan_type"
            parts = custom_id.split(":")
            if len(parts) >= 2:
                user_id = parts[0]
                plan_type = parts[1]
                
                # 确定订阅计划
                plan = SubscriptionPlan.BASE if plan_type == "base" else SubscriptionPlan.PRO
                
                # 更新用户订阅
                result = await subscription_service.create_or_update_subscription(
                    user_id=user_id,
                    plan=plan,
                    payment_method="paypal",
                    external_subscription_id=resource.get("id")
                )
                
                if result["success"]:
                    logger.info(f"Successfully updated subscription for user {user_id} to {plan}")
                    
                    # 发送成功通知到 Slack
                    await send_payment_success_notification(user_id, plan, amount)
                else:
                    logger.error(f"Failed to update subscription for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error handling payment completed: {e}")

async def handle_subscription_activated(resource: dict):
    """处理订阅激活事件"""
    try:
        subscription_id = resource.get("id")
        custom_id = resource.get("custom_id")
        
        logger.info(f"Processing subscription activation: subscription_id={subscription_id}, custom_id={custom_id}")
        
        if custom_id:
            parts = custom_id.split(":")
            if len(parts) >= 2:
                user_id = parts[0]
                plan_type = parts[1]
                
                logger.info(f"Parsed custom_id: user_id={user_id}, plan_type={plan_type}")
                
                # 正确映射计划类型
                if plan_type == "base":
                    plan = SubscriptionPlan.BASE
                elif plan_type == "pro":
                    plan = SubscriptionPlan.PRO
                else:
                    logger.error(f"Unknown plan type: {plan_type}")
                    return
                
                logger.info(f"Mapped plan_type '{plan_type}' to plan '{plan}'")
                
                result = await subscription_service.create_or_update_subscription(
                    user_id=user_id,
                    plan=plan,
                    payment_method="paypal",
                    external_subscription_id=subscription_id
                )
                
                logger.info(f"Subscription service result: {result}")
                
                if result["success"]:
                    logger.info(f"Successfully activated subscription for user {user_id}")
                    
                    # 发送订阅激活/更新通知
                    if result["is_new_subscription"]:
                        logger.info(f"New subscription detected, sending activation notification to user {user_id}")
                        await send_subscription_activated_notification(user_id, plan)
                    else:
                        logger.info(f"Existing subscription updated for user {user_id}, sending update notification")
                        await send_subscription_updated_notification(user_id, plan)
                else:
                    logger.error(f"Failed to activate subscription for user {user_id}: {result}")
            else:
                logger.error(f"Invalid custom_id format: {custom_id}")
        else:
            logger.error("No custom_id found in subscription activation event")
        
    except Exception as e:
        logger.error(f"Error handling subscription activated: {e}")

async def handle_subscription_cancelled(resource: dict):
    """处理订阅取消事件"""
    try:
        subscription_id = resource.get("id")
        
        # 根据 external_subscription_id 查找用户订阅
        # 这里需要在数据库服务中添加相应的查询方法
        # 暂时记录日志
        logger.info(f"Subscription cancelled: {subscription_id}")
        
        # TODO: 实现根据 external_subscription_id 查找并取消用户订阅
        
    except Exception as e:
        logger.error(f"Error handling subscription cancelled: {e}")

async def handle_subscription_suspended(resource: dict):
    """处理订阅暂停事件"""
    try:
        subscription_id = resource.get("id")
        logger.info(f"Subscription suspended: {subscription_id}")
        
        # TODO: 实现订阅暂停逻辑
        
    except Exception as e:
        logger.error(f"Error handling subscription suspended: {e}")

async def handle_subscription_payment_failed(resource: dict):
    """处理订阅支付失败事件"""
    try:
        subscription_id = resource.get("id")
        logger.info(f"Subscription payment failed: {subscription_id}")
        
        # TODO: 实现支付失败处理逻辑，如发送通知、暂停服务等
        
    except Exception as e:
        logger.error(f"Error handling subscription payment failed: {e}")

async def send_payment_success_notification(user_id: str, plan: SubscriptionPlan, amount: str):
    """发送支付成功通知到 Slack"""
    try:
        # 获取用户的 Slack ID
        from services.database_service import DatabaseService
        db = DatabaseService()
        user = await db.get_user_by_id(user_id)
        
        if not user or not user.slack_user_id:
            logger.error(f"User {user_id} not found or missing Slack user ID")
            return
        
        plan_name = "Base Plan" if plan == SubscriptionPlan.BASE else "Premium Plan"
        message = f"🎉 Payment successful! You have successfully subscribed to {plan_name} (${amount}). Thank you for your support!"
        
        await slack_service.send_direct_message(user.slack_user_id, message, team_id=user.slack_team_id)
        
    except Exception as e:
        logger.error(f"Error sending payment success notification: {e}")

async def send_subscription_updated_notification(user_id: str, plan: SubscriptionPlan):
    """发送订阅更新通知到 Slack"""
    try:
        logger.info(f"Attempting to send subscription updated notification for user {user_id}")
        
        # 获取用户的 Slack ID
        from services.database_service import DatabaseService
        db = DatabaseService()
        user = await db.get_user_by_id(user_id)
        
        if not user or not user.slack_user_id:
            logger.error(f"User {user_id} not found or missing Slack user ID")
            return
        
        logger.info(f"Found user with Slack ID: {user.slack_user_id}")
        
        plan_name = "Base Plan" if plan == SubscriptionPlan.BASE else "Premium Plan"
        message = f"🔄 Your {plan_name} subscription has been updated! Your payment has been processed successfully."
        
        logger.info(f"Sending DM to user {user.slack_user_id}: {message}")
        await slack_service.send_direct_message(user.slack_user_id, message, team_id=user.slack_team_id)
        logger.info(f"Successfully sent subscription updated notification to user {user_id}")
        
    except Exception as e:
        logger.error(f"Error sending subscription updated notification: {e}")


async def send_subscription_activated_notification(user_id: str, plan: SubscriptionPlan):
    """发送订阅激活通知到 Slack"""
    try:
        logger.info(f"Attempting to send subscription activated notification for user {user_id}")
        
        # 获取用户的 Slack ID
        from services.database_service import DatabaseService
        db = DatabaseService()
        user = await db.get_user_by_id(user_id)
        
        if not user or not user.slack_user_id:
            logger.error(f"User {user_id} not found or missing Slack user ID")
            return
        
        logger.info(f"Found user with Slack ID: {user.slack_user_id}")
        
        plan_name = "Base Plan" if plan == SubscriptionPlan.BASE else "Premium Plan"
        message = f"✅ Your {plan_name} subscription has been activated! You can now enjoy all the features."
        
        logger.info(f"Sending DM to user {user.slack_user_id}: {message}")
        await slack_service.send_direct_message(user.slack_user_id, message, team_id=user.slack_team_id)
        logger.info(f"Successfully sent subscription activated notification to user {user_id}")
        
    except Exception as e:
        logger.error(f"Error sending subscription activated notification: {e}")