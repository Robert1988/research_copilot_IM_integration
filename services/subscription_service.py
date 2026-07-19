from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import calendar

from services.database_service import db_service
from models import Subscription, SubscriptionPlan, SubscriptionStatus, User

class SubscriptionService:
    def __init__(self):
        # Define plan configurations
        self.plan_configs = {
            SubscriptionPlan.FREE: {
                "name": "Free Plan",
                "price": 0,
                "usage_limit": 20,
                "features": ["Basic message processing", "20 AI generated messages (one time total)"]
            },
            SubscriptionPlan.BASE: {
                "name": "Base Plan",
                "price": 3.99,
                "usage_limit": 40,
                "features": ["Basic message processing", "40 AI generated messages/month", "Core features"]
            },
            SubscriptionPlan.PRO: {
                "name": "Premium Plan",
                "price": 19.99,
                "usage_limit": 200,
                "features": ["Pro message processing", "200 AI generated messages/month", "All features"]
            }
        }
    
    async def has_active_subscription_plan(self, user_id: str, plan: SubscriptionPlan) -> bool:
        """检查用户是否已有指定的活跃订阅计划"""
        try:
            current_subscription = await self.get_user_subscription(user_id)
            
            if not current_subscription:
                return False
            
            # 检查是否是相同计划且状态为活跃
            return (current_subscription.plan == plan and 
                    current_subscription.status == SubscriptionStatus.ACTIVE)
        except Exception as e:
            print(f"Error checking subscription plan: {e}")
            return False

    async def get_user_subscription(self, slack_user_id: str, subscription_id: str  = None) -> Optional[Subscription]:
        """Get user's current subscription"""
        return await db_service.get_user_subscription(slack_user_id, subscription_id)
    
    async def get_user_subscriptions(self, slack_user_id: str) -> Optional[Subscription]:
        """Get user's current subscription"""
        return await db_service.get_user_subscriptions(slack_user_id)

    def _calculate_next_month_same_day(self, current_date: datetime) -> datetime:
        """
        计算下个月的同一天，如果下个月没有相同号，则取下个月的最后一天
        """
        current_day = current_date.day
        current_month = current_date.month
        current_year = current_date.year
        
        # 计算下个月
        if current_month == 12:
            next_month = 1
            next_year = current_year + 1
        else:
            next_month = current_month + 1
            next_year = current_year
        
        # 获取下个月的最后一天
        last_day_of_next_month = calendar.monthrange(next_year, next_month)[1]
        
        # 如果当前日期的天数大于下个月的最后一天，则使用下个月的最后一天
        next_day = min(current_day, last_day_of_next_month)
        
        return datetime(next_year, next_month, next_day, 
                       current_date.hour, current_date.minute, current_date.second, 
                       current_date.microsecond)

    async def create_subscription(self, user_id: str, plan: SubscriptionPlan, slack_user_id: str, external_subscription_id: Optional[str] = None) -> Subscription:
        """Create new subscription for user"""
    
        config = self.plan_configs[plan]
        
        # Calculate expiration date
        expires_at = None
        if plan != SubscriptionPlan.FREE:
            current_time = datetime.utcnow()
            expires_at = self._calculate_next_month_same_day(current_time)  # Monthly subscription
        
        subscription_data = {
            "user_id": user_id,
            "slack_user_id": slack_user_id,
            "external_subscription_id": external_subscription_id or f"free_{user_id}_{int(datetime.utcnow().timestamp())}",  # 为免费订阅生成默认ID
            "plan": plan,
            "status": SubscriptionStatus.ACTIVE if plan == SubscriptionPlan.FREE else SubscriptionStatus.TRIAL,
            "usage_limit": config["usage_limit"],
            "current_usage": 0,
            "expires_at": expires_at
        }
        
        return await db_service.create_subscription(subscription_data)
    
    async def upgrade_subscription(self, user_id: str, new_plan: SubscriptionPlan) -> Optional[Subscription]:
        """Upgrade user's subscription plan"""
        current_subscription = await self.get_user_subscription(user_id)
        if not current_subscription:
            return None
        
        config = self.plan_configs[new_plan]
        
        # Calculate new expiration date
        expires_at = None
        if new_plan != SubscriptionPlan.FREE:
            expires_at = datetime.utcnow() + timedelta(days=30)
        
        update_data = {
            "plan": new_plan,
            "status": SubscriptionStatus.ACTIVE,
            "usage_limit": config["usage_limit"],
            "expires_at": expires_at
        }
        
        return await db_service.update_subscription(current_subscription.id, update_data)
    
    async def cancel_subscription(self, slack_user_id: str, subscription_id: str) -> Optional[Subscription]:
        """Cancel user's subscription"""
        current_subscription = await self.get_user_subscription(slack_user_id, subscription_id)
        if not current_subscription:
            return None
        
        update_data = {
            "status": SubscriptionStatus.CANCELLED,
            "cancelled_at": datetime.utcnow()
        }
        
        return await db_service.update_subscription(current_subscription.id, update_data)
    
    async def check_subscription_validity(self, user_id: str) -> Dict[str, Any]:
        """Check if user's subscription is valid and return status"""
        subscription = await self.get_user_subscription(user_id)
        
        if not subscription:
            return {
                "valid": False,
                "reason": "No subscription found",
                "subscription": None
            }
        
        # Check if subscription is expired
        if subscription.expires_at and subscription.expires_at < datetime.utcnow():
            # Auto-expire the subscription
            await db_service.update_subscription(
                subscription.id,
                {"status": SubscriptionStatus.EXPIRED}
            )
            
            return {
                "valid": False,
                "reason": "Subscription expired",
                "subscription": subscription
            }
        
        # Check if subscription is active
        if subscription.status not in [SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]:
            return {
                "valid": False,
                "reason": f"Subscription status is {subscription.status}",
                "subscription": subscription
            }
        
        # Check usage limits
        monthly_usage = await db_service.get_user_monthly_usage(user_id)
        if monthly_usage >= subscription.usage_limit:
            return {
                "valid": False,
                "reason": "Usage limit exceeded",
                "subscription": subscription,
                "usage": monthly_usage
            }
        
        return {
            "valid": True,
            "subscription": subscription,
            "usage": monthly_usage
        }
    
    async def create_or_update_subscription(
        self, 
        user_id: str, 
        plan: SubscriptionPlan, 
        payment_method: str = "paypal",
        external_subscription_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create or update user subscription after successful payment
        
        Returns:
            Dict with 'success' (bool) and 'is_new_subscription' (bool)
        """
        try:
            current_subscription = await self.get_user_subscription(user_id)
            config = self.plan_configs[plan]
            
            # Calculate expiration date
            expires_at = None
            if plan != SubscriptionPlan.FREE:
                expires_at = datetime.utcnow() + timedelta(days=30)  # Monthly subscription
            # get slack_user_id given user_id

            slack_user_id = await db_service.get_slack_user_id(user_id)
            
            subscription_data = {
                "plan": plan,
                "slack_user_id": slack_user_id,
                "status": SubscriptionStatus.ACTIVE,
                "usage_limit": config["usage_limit"],
                "expires_at": expires_at,
                "payment_method": payment_method,
                "external_subscription_id": external_subscription_id
            }
            
            is_new_subscription = current_subscription is None or current_subscription.plan == SubscriptionPlan.FREE
            
            if current_subscription:
                # Update existing subscription
                await db_service.update_subscription(current_subscription.id, subscription_data)
            else:
                # Create new subscription
                subscription_data["user_id"] = user_id
                subscription_data["current_usage"] = 0
                await db_service.create_subscription(subscription_data)
            
            return {
                "success": True,
                "is_new_subscription": is_new_subscription
            }
        except Exception as e:
            print(f"Error creating/updating subscription: {e}")
            return {
                "success": False,
                "is_new_subscription": False
            }

    async def get_subscription_plans(self) -> Dict[str, Any]:
        """Get all available subscription plans"""
        return {
            "plans": [
                {
                    "id": plan.value,
                    "name": config["name"],
                    "price": config["price"],
                    "usage_limit": config["usage_limit"],
                    "features": config["features"]
                }
                for plan, config in self.plan_configs.items()
            ]
        }
    
    async def process_payment(self, user_id: str, plan: SubscriptionPlan, payment_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process subscription payment (mock implementation)"""
        # This is a mock implementation - integrate with actual payment processor
        # like Stripe, PayPal, etc.
        
        config = self.plan_configs[plan]
        
        # Simulate payment processing
        if payment_data.get("payment_method") == "mock_success":
            # Upgrade subscription
            subscription = await self.upgrade_subscription(user_id, plan)
            
            return {
                "success": True,
                "message": f"Successfully subscribed to {config['name']}",
                "subscription": subscription,
                "transaction_id": f"mock_txn_{datetime.utcnow().timestamp()}"
            }
        else:
            return {
                "success": False,
                "message": "Payment processing failed",
                "error": "Invalid payment method"
            }
    
    async def get_user_subscription_status(self, user_id: str) -> Dict[str, Any]:
        """Get detailed subscription status for user"""
        subscription = await self.get_user_subscription(user_id)
        monthly_usage = await db_service.get_user_monthly_usage(user_id)
        
        if not subscription:
            return {
                "has_subscription": False,
                "plan": SubscriptionPlan.FREE,
                "status": SubscriptionStatus.EXPIRED,
                "usage_count": monthly_usage,
                "usage_limit": 0,
                "expires_at": None
            }
        
        return {
            "has_subscription": True,
            "plan": subscription.plan,
            "status": subscription.status,
            "usage_count": monthly_usage,
            "usage_limit": subscription.usage_limit,
            "usage_percentage": (monthly_usage / subscription.usage_limit * 100) if subscription.usage_limit > 0 else 0,
            "expires_at": subscription.expires_at,
            "created_at": subscription.created_at,
            "cancelled_at": subscription.cancelled_at
        }

# Global subscription service instance
subscription_service = SubscriptionService()