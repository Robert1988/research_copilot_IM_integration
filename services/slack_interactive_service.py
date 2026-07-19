"""
Slack Interactive Message Service
Handles interactive messages, buttons, and user interactions
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from services.paypal_handler import PayPalHandler
from services.subscription_service import subscription_service
from models import User, Subscription
from models import SubscriptionPlan
from config import settings

from services.subscription_service import subscription_service
from services.database_service import db_service
from services.config_user_plan import SUBSCRIPTION_PLANS_CONFIG
import json

logger = logging.getLogger(__name__)

class SlackInteractiveService:
    def __init__(self):
        self.paypal_handler = PayPalHandler()
    
    async def create_subscription_blocks(self, user: User) -> List[Dict[str, Any]]:
        """Create subscription plan blocks for Slack message"""

        blocks = []
        
        # Get all active subscriptions and all cancelled subscriptions
        active_subscriptions = await db_service.get_user_active_subscriptions(user.slack_user_id)
        
        # Get all cancelled subscriptions (not just the latest one)
        db = await db_service.get_db()
        cancelled_subscriptions_data = await db.subscriptions.find(
            {"slack_user_id": user.slack_user_id, "status": "cancelled"},
            sort=[("created_at", -1)]
        ).to_list(None)
        
        cancelled_subscriptions = []
        for cancelled_data in cancelled_subscriptions_data:
            cancelled_data["_id"] = str(cancelled_data["_id"])
            cancelled_subscriptions.append(Subscription(**cancelled_data))
        
        # Header section
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "💎 Subscription Plans"
            }
        })
        
        # Current subscription info - show all active subscriptions
        if active_subscriptions:
            for subscription in active_subscriptions:
                status_emoji = "✅"
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{status_emoji} *Current Plan:* {subscription.plan.value.title()}\n📊 *Status:* {subscription.status.value}"
                    }
                })
        
        # Show cancelled subscriptions that are still valid (within expiry period)
        if cancelled_subscriptions:
            for cancelled_sub in cancelled_subscriptions:
                # Check if this cancelled subscription is not already shown as active
                cancelled_plan_already_active = any(sub.plan == cancelled_sub.plan and sub.status.value == "active" 
                                                  for sub in active_subscriptions)
                
                # Only show if not already active and still within valid period
                if not cancelled_plan_already_active:
                    status_emoji = "❌"
                    expires_text = ""
                    if cancelled_sub.expires_at:
                        if cancelled_sub.expires_at > datetime.utcnow():
                            expires_text = f"\n📅 *Valid until:* {cancelled_sub.expires_at.strftime('%Y-%m-%d')}"
                            
                            blocks.append({
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"{status_emoji} *Cancelled Plan:* {cancelled_sub.plan.value.title()}\n📊 *Status:* {cancelled_sub.status.value}{expires_text}"
                                }
                            })
        
        if active_subscriptions or any(cancelled_sub.expires_at and cancelled_sub.expires_at > datetime.utcnow() for cancelled_sub in cancelled_subscriptions if not any(sub.plan == cancelled_sub.plan and sub.status.value == "active" for sub in active_subscriptions)):
            blocks.append({"type": "divider"})
        
        # Free Plan
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🆓 Free Plan*\n• 20 AI generated messages in total\n• Base features\n*Price: Free*"
            }
        })
        
        # Base Plan (from config)
        base_config = SUBSCRIPTION_PLANS_CONFIG.get("base", {})
        base_plan_details = base_config.get("plan_details")
        if base_plan_details:
            # Check if user has active Base plan
            has_active_base = any(sub.plan == SubscriptionPlan.BASE and sub.status.value == "active" 
                                for sub in active_subscriptions)
            has_cancelled_base = any(cancelled_sub.plan == SubscriptionPlan.BASE and 
                                   cancelled_sub.status.value == "cancelled" and
                                   cancelled_sub.expires_at and cancelled_sub.expires_at > datetime.utcnow()
                                   for cancelled_sub in cancelled_subscriptions)
            
            if has_active_base:
                base_button_text = "Cancel Base Plan"
                base_button_style = "danger"
                base_action_id = "cancel_base_plan"
            elif has_cancelled_base:
                # Cancelled subscription - show reactivate option
                base_button_text = "Reactivate Base Plan"
                base_button_style = "primary"
                base_action_id = "purchase_base_plan"
            else:
                base_button_text = "Purchase Base Plan"
                base_button_style = "primary"
                base_action_id = "purchase_base_plan"
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*⭐ Base Plan*\n• {base_plan_details.monthly_credits} monthly AI generated messages\n• Basic features\n*Price: ${base_plan_details.price}/month*"
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": base_button_text
                    },
                    "style": base_button_style,
                    "action_id": base_action_id,
                    "value": json.dumps({
                        "plan": "base",
                        "price": base_plan_details.price,
                        "user_id": str(user.id),
                        "slack_user_id": user.slack_user_id
                    })
                }
            })
        
        # Pro Plan (from config)
        pro_config = SUBSCRIPTION_PLANS_CONFIG.get("pro", {})
        pro_plan_details = pro_config.get("plan_details")
        if pro_plan_details:
            # Check if user has active Pro plan
            has_active_pro = any(sub.plan == SubscriptionPlan.PRO and sub.status.value == "active" 
                               for sub in active_subscriptions)
            has_cancelled_pro = any(cancelled_sub.plan == SubscriptionPlan.PRO and 
                                  cancelled_sub.status.value == "cancelled" and
                                  cancelled_sub.expires_at and cancelled_sub.expires_at > datetime.utcnow()
                                  for cancelled_sub in cancelled_subscriptions)
            
            if has_active_pro:
                pro_button_text = "Cancel Pro Plan"
                pro_button_style = "danger"
                pro_action_id = "cancel_pro_plan"
            elif has_cancelled_pro:
                # Cancelled subscription - show reactivate option
                pro_button_text = "Reactivate Pro Plan"
                pro_button_style = "primary"
                pro_action_id = "purchase_pro_plan"
            else:
                pro_button_text = "Purchase Pro Plan"
                pro_button_style = "primary"
                pro_action_id = "purchase_pro_plan"
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*🚀 Pro Plan*\n• {pro_plan_details.monthly_credits} monthly AI generated messages\n• All advanced features\n*Price: ${pro_plan_details.price}/month*"
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": pro_button_text
                    },
                    "style": pro_button_style,
                    "action_id": pro_action_id,
                    "value": json.dumps({
                        "plan": "pro",
                        "price": pro_plan_details.price,
                        "user_id": str(user.id),
                        "slack_user_id": user.slack_user_id
                    })
                }
            })
        
        # Footer
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "💳 Secure payment powered by PayPal | 📞 Need help? Send `help` command"
                }
            ]
        })
        
        return blocks
    
    async def create_subscription_message_blocks(self, user: User, current_subscription=None) -> List[Dict[str, Any]]:
        """Create interactive message blocks for subscription options"""
        from services.config_user_plan import SUBSCRIPTION_PLANS_CONFIG
        from services.database_service import DatabaseService
        import asyncio
        
        blocks = []
        
        # Get all active subscriptions and all cancelled subscriptions
        active_subscriptions = await db_service.get_user_active_subscriptions(user.slack_user_id)
        
        # Get all cancelled subscriptions (not just the latest one)
        db = await db_service.get_db()
        cancelled_subscriptions_data = await db.subscriptions.find(
            {"slack_user_id": user.slack_user_id, "status": "cancelled"},
            sort=[("created_at", -1)]
        ).to_list(None)
        
        cancelled_subscriptions = []
        for cancelled_data in cancelled_subscriptions_data:
            cancelled_data["_id"] = str(cancelled_data["_id"])
            cancelled_subscriptions.append(Subscription(**cancelled_data))
        
        # Header section
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "💎 Subscription Plans"
            }
        })
        
        # Current subscription info - show all active subscriptions
        if active_subscriptions:
            for subscription in active_subscriptions:
                status_emoji = "✅"
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{status_emoji} *Current Plan:* {subscription.plan.value.title()}\n📊 *Status:* {subscription.status.value}"
                    }
                })
        
        # Show cancelled subscriptions that are still valid (within expiry period)
        if cancelled_subscriptions:
            for cancelled_sub in cancelled_subscriptions:
                # Check if this cancelled subscription is not already shown as active
                cancelled_plan_already_active = any(sub.plan == cancelled_sub.plan and sub.status.value == "active" 
                                                  for sub in active_subscriptions)
                
                # Only show if not already active and still within valid period
                if not cancelled_plan_already_active:
                    status_emoji = "❌"
                    expires_text = ""
                    if cancelled_sub.expires_at:
                        # Check if still valid
                        if cancelled_sub.expires_at > datetime.utcnow():
                            expires_text = f"\n📅 *Valid until:* {cancelled_sub.expires_at.strftime('%Y-%m-%d')}"
                            
                            blocks.append({
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"{status_emoji} *Cancelled Plan:* {cancelled_sub.plan.value.title()}\n📊 *Status:* {cancelled_sub.status.value}{expires_text}"
                                }
                            })
        
        if active_subscriptions or any(cancelled_sub.expires_at and cancelled_sub.expires_at > datetime.utcnow() for cancelled_sub in cancelled_subscriptions if not any(sub.plan == cancelled_sub.plan and sub.status.value == "active" for sub in active_subscriptions)):
            blocks.append({"type": "divider"})
        
        # Free Plan
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🆓 Free Plan*\n• 20 AI generated messages in total\n• Base features\n*Price: Free*"
            }
        })
        
        # Base Plan (from config)
        base_config = SUBSCRIPTION_PLANS_CONFIG.get("base", {})
        base_plan_details = base_config.get("plan_details")
        if base_plan_details:
            # Check if user has active Base plan
            has_active_base = any(sub.plan == SubscriptionPlan.BASE and sub.status.value == "active" 
                                for sub in active_subscriptions)
            has_cancelled_base = any(cancelled_sub.plan == SubscriptionPlan.BASE and 
                                   cancelled_sub.status.value == "cancelled" and
                                   cancelled_sub.expires_at and cancelled_sub.expires_at > datetime.utcnow()
                                   for cancelled_sub in cancelled_subscriptions)
            
            if has_active_base:
                base_button_text = "Cancel Base Plan"
                base_button_style = "danger"
                base_action_id = "cancel_base_plan"
            elif has_cancelled_base:
                # Cancelled subscription - show reactivate option
                base_button_text = "Reactivate Base Plan"
                base_button_style = "primary"
                base_action_id = "purchase_base_plan"
            else:
                base_button_text = "Purchase Base Plan"
                base_button_style = "primary"
                base_action_id = "purchase_base_plan"
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*⭐ Base Plan*\n {base_plan_details.monthly_credits} monthly AI generated messages\n• Basic features\n*Price: ${base_plan_details.price}/month*"
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": base_button_text
                    },
                    "style": base_button_style,
                    "action_id": base_action_id,
                    "value": json.dumps({
                        "plan": "base",
                        "price": base_plan_details.price,
                        "user_id": str(user.id),
                        "slack_user_id": user.slack_user_id
                    })
                }
            })
        
        # Pro Plan (from config)
        pro_config = SUBSCRIPTION_PLANS_CONFIG.get("pro", {})
        pro_plan_details = pro_config.get("plan_details")
        if pro_plan_details:
            # Check if user has active Pro plan
            has_active_pro = any(sub.plan == SubscriptionPlan.PRO and sub.status.value == "active" 
                               for sub in active_subscriptions)
            has_cancelled_pro = any(cancelled_sub.plan == SubscriptionPlan.PRO and 
                                  cancelled_sub.status.value == "cancelled" and
                                  cancelled_sub.expires_at and cancelled_sub.expires_at > datetime.utcnow()
                                  for cancelled_sub in cancelled_subscriptions)
            
            if has_active_pro:
                pro_button_text = "Cancel Pro Plan"
                pro_button_style = "danger"
                pro_action_id = "cancel_pro_plan"
            elif has_cancelled_pro:
                # Cancelled subscription - show reactivate option
                pro_button_text = "Reactivate Pro Plan"
                pro_button_style = "primary"
                pro_action_id = "purchase_pro_plan"
            else:
                pro_button_text = "Purchase Pro Plan"
                pro_button_style = "primary"
                pro_action_id = "purchase_pro_plan"
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*🚀 Pro Plan*\n• {pro_plan_details.monthly_credits} monthly AI generated messages\n• All advanced features\n*Price: ${pro_plan_details.price}/month*"
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": pro_button_text
                    },
                    "style": pro_button_style,
                    "action_id": pro_action_id,
                    "value": json.dumps({
                        "plan": "pro",
                        "price": pro_plan_details.price,
                        "user_id": str(user.id),
                        "slack_user_id": user.slack_user_id
                    })
                }
            })
        
        # Footer
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "💳 Secure payment powered by PayPal | 📞 Need help? Send `help` command"
                }
            ]
        })
        
        return blocks
    
    def create_upgrade_confirmation_blocks(self, plan: str, price: float, payment_url: str) -> List[Dict[str, Any]]:
        """Create confirmation message blocks after generating payment URL"""
        
        plan_emoji = "⭐" if plan == "base" else "🚀"
        plan_name = "Base Plan" if plan == "base" else "Premium Plan"
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{plan_emoji} Subscribe to {plan_name}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Plan:* {plan_name}\n*Price:* ${price}/month\n*Payment Method:* PayPal"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "🔗 *Click the link below to complete payment:*"
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Go to PayPal Payment"
                    },
                    "style": "primary",
                    "url": payment_url,
                    "action_id": "open_payment_url"
                }
            },
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "💡 *Tip:* Your subscription will be activated automatically after payment completion. Contact customer service if you have any questions."
                    }
                ]
            }
        ]
        
        return blocks
    
    def create_payment_success_blocks(self, plan: str) -> List[Dict[str, Any]]:
        """Create success message blocks after payment completion"""
        
        plan_emoji = "⭐" if plan == "base" else "🚀"
        plan_name = "Base Plan" if plan == "base" else "Pro Plan"
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "✅ Payment Successful!"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🎉 *Congratulations! You have successfully subscribed to {plan_emoji} {plan_name}*\n\nYour subscription is now active and you can enjoy all features!"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*What you can do next:*\n• Send `billing` to view billing information\n• Send `status` to check usage status\n• Start using all features"
                }
            },
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "🙏 Thank you for your support! Please contact us if you have any questions."
                    }
                ]
            }
        ]
        
        return blocks
    
    async def handle_button_interaction(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle button click interactions"""
        try:
            action = payload.get("actions", [{}])[0]
            action_id = action.get("action_id")
            action_value = action.get("value")
            
            user_info = payload.get("user", {})
            user_id = user_info.get("id")
            
            logger.info(f"Handling button interaction: {action_id} for user {user_id}")
            
            if action_id in ["purchase_base_plan", "purchase_pro_plan"]:
                response = await self._handle_purchase_button(action_value, payload)
                logger.info(f"Purchase button response: {response}")
                return response
            elif action_id in ["cancel_base_plan", "cancel_pro_plan"]:
                response = await self._handle_cancel_button(action_id, action_value, payload)
                logger.info(f"Cancel button response: {response}")
                return response
            elif action_id in ["confirm_cancel_base_plan", "confirm_cancel_pro_plan"]:
                response = await self._handle_confirm_cancel_button(action_id, action_value, payload)
                logger.info(f"Confirm cancel button response: {response}")
                return response
            elif action_id == "keep_subscription":
                response = await self._handle_keep_subscription_button(action_value, payload)
                logger.info(f"Keep subscription button response: {response}")
                return response
            elif action_id == "view_subscription_status":
                response = await self._handle_view_subscription_status(payload)
                logger.info(f"View subscription status response: {response}")
                return response
            
            response = {
                "response_type": "ephemeral",
                "text": "❌ Unknown action type"
            }
            logger.info(f"Unknown action response: {response}")
            return response
            
        except Exception as e:
            logger.error(f"Error handling button interaction: {str(e)}")
            response = {
                "response_type": "ephemeral",
                "text": f"❌ Error processing request: {str(e)}"
            }
            logger.info(f"Error response: {response}")
            return response
    
    async def handle_interactive_action(self, action_id: str, action_value: str, user_id: str) -> Optional[List[Dict[str, Any]]]:
        """Handle interactive action and return response blocks"""
        try:
            logger.info(f"Handling interactive action: {action_id} for user {user_id}")
            
            if action_id in ["purchase_base_plan", "purchase_pro_plan"]:
                # Create a mock payload for the existing method
                payload = {
                    "user": {"id": user_id},
                    "actions": [{"action_id": action_id, "value": action_value}]
                }
                
                # Call the existing purchase button handler
                response = await self._handle_purchase_button(action_value, payload)
                
                # Extract blocks from response if available
                if isinstance(response, dict) and "blocks" in response:
                    return response["blocks"]
                elif isinstance(response, dict) and "text" in response:
                    # Convert text response to blocks format
                    return [{
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": response["text"]
                        }
                    }]
            elif action_id in ["cancel_base_plan", "cancel_pro_plan"]:
                # Create a mock payload for the existing method
                payload = {
                    "user": {"id": user_id},
                    "actions": [{"action_id": action_id, "value": action_value}]
                }
                response = await self._handle_cancel_button(action_id, action_value, payload)
                return response.get("blocks") if response else None
            elif action_id in ["confirm_cancel_base_plan", "confirm_cancel_pro_plan"]:
                # Create a mock payload for the existing method
                payload = {
                    "user": {"id": user_id},
                    "actions": [{"action_id": action_id, "value": action_value}]
                }
                response = await self._handle_confirm_cancel_button(action_id, action_value, payload)
                return response.get("blocks") if response else None
            elif action_id == "keep_subscription":
                # Create a mock payload for the existing method
                payload = {
                    "user": {"id": user_id},
                    "actions": [{"action_id": action_id, "value": action_value}]
                }
                response = await self._handle_keep_subscription_button(action_value, payload)
                return response.get("blocks") if response else None
                
            return None
            
        except Exception as e:
            logger.error(f"Error handling interactive action {action_id}: {str(e)}")
            return [{
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"❌ Error processing request: {str(e)}"
                }
            }]

    async def _handle_purchase_button(self, action_value: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle purchase button clicks"""
        try:
            # Parse action value
            purchase_data = json.loads(action_value)
            plan = purchase_data.get("plan")
            price = purchase_data.get("price")
            user_id = purchase_data.get("user_id")
            
            # Get user info from payload
            user_info = payload.get("user", {})
            slack_user_id = user_info.get("id")
            user_name = user_info.get("name", "Unknown")
            
            logger.info(f"Processing purchase for plan: {plan}, user: {slack_user_id}")
            
            # Create PayPal order
            order_data = {
                "user_id": user_id,
                "slack_user_id": slack_user_id,
                "user_name": user_name,
                "plan": plan,
                "amount": price,
                "currency": "USD",
                "description": f"Subscribe to {plan.title()} Plan - ${price}/month"
            }
            
            # Check if user already has the same active subscription plan
            from models import SubscriptionPlan as ModelSubscriptionPlan
            target_plan = ModelSubscriptionPlan.BASE if plan == "base" else ModelSubscriptionPlan.PRO
            
            from services.subscription_service import subscription_service
            has_same_plan = await subscription_service.has_active_subscription_plan(user_id, target_plan)
            
            if has_same_plan:
                # Return error message for duplicate subscription
                return {
                    "response_type": "ephemeral",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"❌ *You already have an active {plan.title()} Plan subscription*\n\nYou don't need to purchase the same subscription plan again. If you want to upgrade to a higher plan, please select a different plan."
                            }
                        }
                    ]
                }
            
            # Use plan directly (already in correct format)
            mapped_plan = plan
            
            # Create PayPal order request
            from models import PayPalOrderRequest
            order_request = PayPalOrderRequest(
                description=f"Subscribe to {mapped_plan.title()} Plan - ${price}/month",
                is_subscription=True,
                subscription_plan_type=mapped_plan,
                return_url="https://www.alignspires.com/slack/paypal/success",
                cancel_url="https://www.alignspires.com/slack/paypal/cancel"
            )
            
            # Generate PayPal subscription order
            paypal_response = await self.paypal_handler.create_order(
                order_request=order_request,
                user_id=user_id
            )
            
            if paypal_response.success and paypal_response.approval_url:
                # Create confirmation blocks with payment URL
                blocks = self.create_upgrade_confirmation_blocks(
                    plan=plan,
                    price=price,
                    payment_url=paypal_response.approval_url
                )
                
                return {
                    "response_type": "ephemeral",
                    "blocks": blocks
                }
            elif paypal_response.success and paypal_response.links:
                # Fallback: extract approval URL from links if not directly available
                approval_url = None
                for link in paypal_response.links:
                    if link.rel == "approve":
                        approval_url = link.href
                        break
                
                if approval_url:
                    blocks = self.create_upgrade_confirmation_blocks(
                        plan=plan,
                        price=price,
                        payment_url=approval_url
                    )
                    
                    return {
                        "response_type": "ephemeral",
                        "blocks": blocks
                    }
                else:
                    error_msg = "Unable to get payment link"
                    return {
                        "response_type": "ephemeral",
                        "text": f"❌ {error_msg}"
                    }
            else:
                error_msg = paypal_response.error_message or "Failed to create payment order"
                return {
                    "response_type": "ephemeral",
                    "text": f"❌ {error_msg}"
                }
                
        except Exception as e:
            logger.error(f"Error handling purchase button: {str(e)}")
            return {
                "response_type": "ephemeral",
                "text": f"❌ Error processing purchase request: {str(e)}"
            }
    
    async def _handle_cancel_button(self, action_id: str, action_value: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle cancel subscription button clicks"""
        try:
            user_info = payload.get("user", {})
            user_id = user_info.get("id")
            
            logger.info(f"Processing cancel button: {action_id} for user {user_id}")
            
            # Determine which plan to cancel
            plan_to_cancel = "base" if action_id == "cancel_base_plan" else "pro"
            plan_name = "Base Plan" if plan_to_cancel == "base" else "Pro Plan"
            
            # Here you would typically:
            # 1. Call PayPal API to cancel the subscription
            # 2. Update the user's subscription status in your database
            # 3. Send confirmation
            
            # For now, return a confirmation message
            return {
                "response_type": "ephemeral",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"🔄 Canceling your {plan_name} subscription..."
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "⚠️ Please note: After canceling your subscription, you will lose access to plan features at the end of the current billing cycle."
                        }
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "Confirm Cancel"
                                },
                                "style": "danger",
                                "action_id": f"confirm_cancel_{plan_to_cancel}_plan",
                                "value": plan_to_cancel
                            },
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "Keep Subscription"
                                },
                                "action_id": "keep_subscription",
                                "value": plan_to_cancel
                            }
                        ]
                    }
                ]
            }
            
        except Exception as e:
            logger.error(f"Error handling cancel button: {str(e)}")
            return {
                "response_type": "ephemeral",
                "text": f"❌ Error processing cancel request: {str(e)}"
            }
    
    async def _handle_confirm_cancel_button(self, action_id: str, action_value: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle confirm cancel subscription button clicks"""
        try:
            user_info = payload.get("user", {})
            slack_user_id = user_info.get("id")  # 修复：使用 "id" 而不是 "slack_user_id"
            
            logger.info(f"Processing confirm cancel button: {action_id} for Slack user {slack_user_id}")

            # Determine which plan to cancel
            plan_to_cancel = "base" if "base" in action_id else "pro"
            plan_name = "Base Plan" if plan_to_cancel == "base" else "Pro Plan"
            
            user = await db_service.get_user_by_slack_id(slack_user_id)
            
            if not user:
                logger.error(f"User not found for Slack ID: {slack_user_id}")
                return {
                    "response_type": "ephemeral",
                    "text": "❌ User information not found, unable to cancel subscription"
                }
            
            user_id = user.id
            # logger.info(f"Found database user ID: {user_id} for Slack user: {slack_user_id}")
            
            # Find active PayPal subscription for this user
            from services.paypal_handler import PayPalHandler
            paypal_handler = PayPalHandler()
            orders_collection = await paypal_handler._get_orders_collection()
            
            # Find active subscription order for the user with matching plan type
            subscription_plan_type = "base" if plan_to_cancel == "base" else "pro"
            order_doc = await orders_collection.find_one({
                "user_id": user_id,
                "is_subscription": True,
                "subscription_plan_type": subscription_plan_type,
                "status": {"$in": ["ACTIVE"]}
            })
            
            if not order_doc:
                logger.warning(f"No active subscription found for user {user_id} with plan {subscription_plan_type}")
                return {
                    "response_type": "ephemeral",
                    "text": f"❌ No active {plan_name} subscription found"
                }
            
            subscription_id = order_doc.get("order_id")
            logger.info(f"Found subscription to cancel: {subscription_id}")
            
            # Cancel the PayPal subscription
            cancel_success = await paypal_handler._cancel_paypal_subscription(subscription_id)
            
            if cancel_success:
                # Update order status in database
                await orders_collection.update_one(
                    {"order_id": subscription_id},
                    {
                        "$set": {
                            "status": "CANCELLED",
                            "cancelled_at": datetime.utcnow(),
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
                
                # Update user subscription status in the subscription service
                from services.subscription_service import subscription_service
                await subscription_service.cancel_subscription(slack_user_id, subscription_id)
                
                logger.info(f"Successfully cancelled subscription {subscription_id} for user {user_id}")
                
                return {
                    "response_type": "ephemeral",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"✅ Your {plan_name} subscription has been successfully canceled"
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "📅 You can continue using premium features until the end of the current billing cycle.\n\nIf you change your mind, you can resubscribe at any time."
                            }
                        }
                    ]
                }
            else:
                logger.error(f"Failed to cancel PayPal subscription {subscription_id}")
                return {
                    "response_type": "ephemeral",
                    "text": f"❌ Failed to cancel {plan_name} subscription, please try again later or contact support"
                }
            
        except Exception as e:
            logger.error(f"Error handling confirm cancel button: {str(e)}")
            return {
                "response_type": "ephemeral",
                "text": f"❌ Error processing confirm cancel request: {str(e)}"
            }
    
    async def _handle_keep_subscription_button(self, action_value: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle keep subscription button clicks"""
        try:
            user_info = payload.get("user", {})
            user_id = user_info.get("id")
            
            logger.info(f"Processing keep subscription button for user {user_id}")
            
            plan_name = "Base Plan" if action_value == "base" else "Pro Plan"
            
            return {
                "response_type": "ephemeral",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"🎉 Great! You will continue to enjoy all the features of {plan_name}."
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "Thank you for continuing to support our service! If you have any questions or suggestions, please feel free to contact us."
                        }
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "View Subscription Details"
                                },
                                "action_id": "view_subscription_details",
                                "value": "view_details"
                            }
                        ]
                    }
                ]
            }
            
        except Exception as e:
            logger.error(f"Error handling keep subscription button: {str(e)}")
            return {
                "response_type": "ephemeral",
                "text": f"❌ Error processing keep subscription request: {str(e)}"
            }
    
    async def _handle_view_subscription_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle view subscription status button clicks"""
        try:
            user_info = payload.get("user", {})
            slack_user_id = user_info.get("id")
            
            logger.info(f"Processing view subscription status for Slack user {slack_user_id}")
            
            user = await db_service.get_user_by_slack_id(slack_user_id)
            
            if not user:
                return {
                    "response_type": "ephemeral",
                    "text": "❌ User not found. Please make sure you're registered."
                }
            
            # Get current subscription
            current_subscription = await subscription_service.get_user_subscriptions(user.slack_user_id)
            
            if not current_subscription:
                return {
                    "response_type": "ephemeral",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "📊 *Subscription Status*\n\n🆓 *Current Plan:* Free Plan\n📈 *Status:* Active\n💬 *Messages Remaining:* Check your usage with `/status` command"
                            }
                        },
                        {
                            "type": "divider"
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "🚀 *Upgrade to get more features:*\n• Unlimited AI messages\n• Priority support\n• Advanced features"
                            }
                        }
                    ]
                }
            
            # Format subscription status
            status_emoji = "✅" if current_subscription.status.value == "active" else "⏳" if current_subscription.status.value == "trial" else "❌"
            plan_name = current_subscription.plan.value.title()
            
            # Get subscription details from config
            from services.config_user_plan import SUBSCRIPTION_PLANS_CONFIG
            plan_key = "base" if current_subscription.plan.value == "base" else "pro"
            plan_config = SUBSCRIPTION_PLANS_CONFIG.get(plan_key, {})
            plan_details = plan_config.get("plan_details")
            
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"📊 *Subscription Status*\n\n{status_emoji} *Current Plan:* {plan_name}\n📈 *Status:* {current_subscription.status.value.title()}"
                    }
                }
            ]
            
            # Add plan details if available
            if plan_details:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"💎 *Plan Features:*\n• {plan_details.monthly_credits} monthly AI messages\n• Basic features\n💰 *Price:* ${plan_details.price}/month"
                    }
                })
            
            # Add subscription dates if available
            if hasattr(current_subscription, 'created_at') and current_subscription.created_at:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"📅 *Subscription Started:* {current_subscription.created_at.strftime('%Y-%m-%d')}"
                    }
                })
            
            # Add renewal info for active subscriptions
            if current_subscription.status.value == "active":
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "🔄 *Renewal:* Your subscription will automatically renew monthly"
                    }
                })
            
            return {
                "response_type": "ephemeral",
                "blocks": blocks
            }
            
        except Exception as e:
            logger.error(f"Error handling view subscription status: {str(e)}")
            return {
                "response_type": "ephemeral",
                "text": f"❌ Error retrieving subscription status: {str(e)}"
            }

# Global interactive service instance
slack_interactive_service = SlackInteractiveService()