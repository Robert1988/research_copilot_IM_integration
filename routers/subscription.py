from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any

from routers.auth import get_current_user
from services.subscription_service import subscription_service
from models import User, SubscriptionPlan, SubscriptionResponse

router = APIRouter()

class SubscriptionUpgradeRequest(BaseModel):
    plan: SubscriptionPlan
    payment_method: str = "mock_success"  # For demo purposes
    payment_data: Dict[str, Any] = {}

class PaymentRequest(BaseModel):
    plan: SubscriptionPlan
    payment_method: str
    payment_token: str
    billing_address: Dict[str, Any] = {}

@router.get("/plans")
async def get_subscription_plans():
    """Get all available subscription plans"""
    return await subscription_service.get_subscription_plans()

@router.get("/status")
async def get_subscription_status(current_user: User = Depends(get_current_user)):
    """Get current user's subscription status"""
    status = await subscription_service.get_user_subscription_status(current_user.id)
    return status

@router.get("/current")
async def get_current_subscription(current_user: User = Depends(get_current_user)):
    """Get current user's subscription details"""
    subscription = await subscription_service.get_user_subscription(current_user.id)
    
    if not subscription:
        raise HTTPException(status_code=404, detail="No subscription found")
    
    return SubscriptionResponse(
        id=subscription.id,
        plan=subscription.plan,
        status=subscription.status,
        usage_count=await subscription_service.db_service.get_user_monthly_usage(current_user.id),
        usage_limit=subscription.usage_limit,
        expires_at=subscription.expires_at,
        created_at=subscription.created_at
    )

@router.post("/upgrade")
async def upgrade_subscription(
    request: SubscriptionUpgradeRequest,
    current_user: User = Depends(get_current_user)
):
    """Upgrade user's subscription plan"""
    
    # Check if user already has the requested plan
    current_subscription = await subscription_service.get_user_subscription(current_user.id)
    if current_subscription and current_subscription.plan == request.plan:
        raise HTTPException(status_code=400, detail="Already subscribed to this plan")
    
    # Process payment and upgrade
    result = await subscription_service.process_payment(
        user_id=current_user.id,
        plan=request.plan,
        payment_data={"payment_method": request.payment_method, **request.payment_data}
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    return {
        "message": result["message"],
        "subscription": result["subscription"],
        "transaction_id": result.get("transaction_id")
    }

@router.post("/cancel")
async def cancel_subscription(current_user: User = Depends(get_current_user)):
    """Cancel user's subscription"""
    
    subscription = await subscription_service.cancel_subscription(current_user.id)
    
    if not subscription:
        raise HTTPException(status_code=404, detail="No active subscription found")
    
    return {
        "message": "Subscription cancelled successfully",
        "subscription": subscription
    }

@router.post("/reactivate")
async def reactivate_subscription(current_user: User = Depends(get_current_user)):
    """Reactivate cancelled subscription"""
    
    current_subscription = await subscription_service.get_user_subscription(current_user.id)
    
    if not current_subscription:
        raise HTTPException(status_code=404, detail="No subscription found")
    
    if current_subscription.status != "cancelled":
        raise HTTPException(status_code=400, detail="Subscription is not cancelled")
    
    # Reactivate subscription (this would typically involve payment processing)
    updated_subscription = await subscription_service.upgrade_subscription(
        current_user.id,
        current_subscription.plan
    )
    
    return {
        "message": "Subscription reactivated successfully",
        "subscription": updated_subscription
    }

@router.get("/usage")
async def get_usage_stats(current_user: User = Depends(get_current_user)):
    """Get user's usage statistics"""
    
    subscription = await subscription_service.get_user_subscription(current_user.id)
    monthly_usage = await subscription_service.db_service.get_user_monthly_usage(current_user.id)
    usage_stats = await subscription_service.db_service.get_user_usage_stats(current_user.id, days=30)
    
    return {
        "current_month_usage": monthly_usage,
        "usage_limit": subscription.usage_limit if subscription else 0,
        "usage_percentage": (monthly_usage / subscription.usage_limit * 100) if subscription and subscription.usage_limit > 0 else 0,
        "daily_stats": [
            {
                "date": stat.date.isoformat(),
                "messages_received": stat.messages_received,
                "messages_sent": stat.messages_sent,
                "total_messages": stat.messages_received + stat.messages_sent,
                "errors_count": stat.errors_count,
                "avg_processing_time_ms": stat.total_processing_time_ms // max(stat.messages_received + stat.messages_sent, 1)
            }
            for stat in usage_stats
        ]
    }

@router.post("/webhook/payment")
async def handle_payment_webhook(request: Dict[str, Any]):
    """Handle payment processor webhooks (Stripe, PayPal, etc.)"""
    
    # This is where you'd handle real payment webhooks
    # For now, it's a placeholder
    
    event_type = request.get("type")
    
    if event_type == "payment.succeeded":
        # Handle successful payment
        user_id = request.get("user_id")
        plan = request.get("plan")
        
        if user_id and plan:
            await subscription_service.upgrade_subscription(user_id, SubscriptionPlan(plan))
    
    elif event_type == "payment.failed":
        # Handle failed payment
        pass
    
    return {"status": "received"}

@router.get("/billing-history")
async def get_billing_history(current_user: User = Depends(get_current_user)):
    """Get user's billing history"""
    
    # This would typically fetch from a billing/payment service
    # For now, return mock data
    
    return {
        "billing_history": [
            {
                "id": "inv_001",
                "date": "2024-01-01T00:00:00Z",
                "amount": 9.99,
                "plan": "base",
                "status": "paid",
                "invoice_url": "https://example.com/invoice/001"
            }
        ]
    }