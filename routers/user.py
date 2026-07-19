from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List
from datetime import datetime, timedelta

from routers.auth import get_current_user
from services.database_service import db_service
from services.message_service import message_service
from services.subscription_service import subscription_service
from models import User, UserResponse, MessageLog

router = APIRouter()

@router.get("/profile", response_model=UserResponse)
async def get_user_profile(current_user: User = Depends(get_current_user)):
    """Get current user's profile information"""
    
    subscription = await subscription_service.get_user_subscription(current_user.id)
    monthly_usage = await db_service.get_user_monthly_usage(current_user.id)
    
    return UserResponse(
        id=current_user.id,
        slack_user_id=current_user.slack_user_id,
        name=current_user.name,
        email=current_user.email,
        subscription_status=subscription.status if subscription else "expired",
        subscription_plan=subscription.plan if subscription else "free",
        usage_count=monthly_usage,
        usage_limit=subscription.usage_limit if subscription else 0,
        created_at=current_user.created_at
    )

@router.put("/profile")
async def update_user_profile(
    name: Optional[str] = None,
    email: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """Update user profile information"""
    
    update_data = {}
    if name is not None:
        update_data["name"] = name
    if email is not None:
        update_data["email"] = email
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")
    
    updated_user = await db_service.update_user(current_user.id, update_data)
    
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "message": "Profile updated successfully",
        "user": {
            "id": updated_user.id,
            "name": updated_user.name,
            "email": updated_user.email,
            "updated_at": updated_user.updated_at
        }
    }

@router.get("/messages")
async def get_message_history(
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user)
):
    """Get user's message history"""
    
    messages = await message_service.get_user_message_history(current_user, limit)
    
    return {
        "messages": messages,
        "total": len(messages)
    }

@router.get("/stats")
async def get_user_stats(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user)
):
    """Get user's usage statistics"""
    
    # Get subscription info
    subscription = await subscription_service.get_user_subscription(current_user.id)
    monthly_usage = await db_service.get_user_monthly_usage(current_user.id)
    
    # Get usage stats for specified period
    usage_stats = await db_service.get_user_usage_stats(current_user.id, days)
    
    # Calculate totals
    total_messages_received = sum(stat.messages_received for stat in usage_stats)
    total_messages_sent = sum(stat.messages_sent for stat in usage_stats)
    total_errors = sum(stat.errors_count for stat in usage_stats)
    total_processing_time = sum(stat.total_processing_time_ms for stat in usage_stats)
    
    # Calculate averages
    total_messages = total_messages_received + total_messages_sent
    avg_processing_time = total_processing_time / max(total_messages, 1)
    
    return {
        "period_days": days,
        "subscription": {
            "plan": subscription.plan if subscription else "free",
            "status": subscription.status if subscription else "expired",
            "usage_limit": subscription.usage_limit if subscription else 0
        },
        "current_month": {
            "usage_count": monthly_usage,
            "usage_limit": subscription.usage_limit if subscription else 0,
            "usage_percentage": (monthly_usage / subscription.usage_limit * 100) if subscription and subscription.usage_limit > 0 else 0
        },
        "period_totals": {
            "messages_received": total_messages_received,
            "messages_sent": total_messages_sent,
            "total_messages": total_messages,
            "errors_count": total_errors,
            "total_processing_time_ms": total_processing_time,
            "avg_processing_time_ms": round(avg_processing_time, 2)
        },
        "daily_breakdown": [
            {
                "date": stat.date.isoformat(),
                "messages_received": stat.messages_received,
                "messages_sent": stat.messages_sent,
                "total_messages": stat.messages_received + stat.messages_sent,
                "errors_count": stat.errors_count,
                "processing_time_ms": stat.total_processing_time_ms,
                "avg_processing_time_ms": round(
                    stat.total_processing_time_ms / max(stat.messages_received + stat.messages_sent, 1), 2
                )
            }
            for stat in usage_stats
        ]
    }

@router.delete("/account")
async def delete_user_account(current_user: User = Depends(get_current_user)):
    """Delete user account and all associated data"""
    
    # This is a destructive operation - in production, you might want to:
    # 1. Require additional confirmation
    # 2. Soft delete instead of hard delete
    # 3. Retain some data for legal/compliance reasons
    
    try:
        # Cancel subscription first
        await subscription_service.cancel_subscription(current_user.id)
        
        # Mark user as inactive instead of deleting
        await db_service.update_user(current_user.id, {
            "is_active": False,
            "deleted_at": datetime.utcnow(),
            "access_token": "",  # Clear sensitive data
            "refresh_token": ""
        })
        
        return {"message": "Account deleted successfully"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to delete account")

@router.post("/deactivate")
async def deactivate_account(current_user: User = Depends(get_current_user)):
    """Temporarily deactivate user account"""
    
    updated_user = await db_service.update_user(current_user.id, {
        "is_active": False
    })
    
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"message": "Account deactivated successfully"}

@router.post("/reactivate")
async def reactivate_account(current_user: User = Depends(get_current_user)):
    """Reactivate user account"""
    
    updated_user = await db_service.update_user(current_user.id, {
        "is_active": True
    })
    
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"message": "Account reactivated successfully"}

@router.get("/activity")
async def get_user_activity(
    days: int = Query(7, ge=1, le=30),
    current_user: User = Depends(get_current_user)
):
    """Get user's recent activity summary"""
    
    # Get recent message logs
    recent_messages = await db_service.get_user_message_history(current_user.id, limit=100)
    
    # Filter by date range
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    filtered_messages = [msg for msg in recent_messages if msg.timestamp >= cutoff_date]
    
    # Group by date
    activity_by_date = {}
    for msg in filtered_messages:
        date_key = msg.timestamp.date().isoformat()
        if date_key not in activity_by_date:
            activity_by_date[date_key] = {
                "date": date_key,
                "messages_received": 0,
                "messages_sent": 0,
                "errors": 0,
                "avg_processing_time": 0,
                "processing_times": []
            }
        
        if msg.message_type == "received":
            activity_by_date[date_key]["messages_received"] += 1
        elif msg.message_type == "sent":
            activity_by_date[date_key]["messages_sent"] += 1
        
        if msg.error:
            activity_by_date[date_key]["errors"] += 1
        
        if msg.processing_time_ms:
            activity_by_date[date_key]["processing_times"].append(msg.processing_time_ms)
    
    # Calculate averages
    for date_data in activity_by_date.values():
        if date_data["processing_times"]:
            date_data["avg_processing_time"] = round(
                sum(date_data["processing_times"]) / len(date_data["processing_times"]), 2
            )
        del date_data["processing_times"]  # Remove raw data
    
    # Sort by date
    activity_list = sorted(activity_by_date.values(), key=lambda x: x["date"], reverse=True)
    
    return {
        "period_days": days,
        "total_activity_days": len(activity_list),
        "activity": activity_list
    }

@router.get("/export")
async def export_user_data(current_user: User = Depends(get_current_user)):
    """Export all user data (GDPR compliance)"""
    
    # Get all user data
    subscription = await subscription_service.get_user_subscription(current_user.id)
    messages = await message_service.get_user_message_history(current_user, limit=1000)
    usage_stats = await db_service.get_user_usage_stats(current_user.id, days=365)
    
    export_data = {
        "user_profile": {
            "id": current_user.id,
            "slack_user_id": current_user.slack_user_id,
            "name": current_user.name,
            "email": current_user.email,
            "created_at": current_user.created_at.isoformat(),
            "updated_at": current_user.updated_at.isoformat(),
            "is_active": current_user.is_active
        },
        "subscription": {
            "plan": subscription.plan if subscription else None,
            "status": subscription.status if subscription else None,
            "created_at": subscription.created_at.isoformat() if subscription else None,
            "expires_at": subscription.expires_at.isoformat() if subscription and subscription.expires_at else None
        },
        "messages": [
            {
                "id": msg["id"],
                "message_type": msg["message_type"],
                "original_message": msg["original_message"],
                "response_message": msg["response_message"],
                "timestamp": msg["timestamp"].isoformat() if isinstance(msg["timestamp"], datetime) else msg["timestamp"],
                "processing_time_ms": msg["processing_time_ms"],
                "error": msg["error"]
            }
            for msg in messages
        ],
        "usage_statistics": [
            {
                "date": stat.date.isoformat(),
                "messages_received": stat.messages_received,
                "messages_sent": stat.messages_sent,
                "total_processing_time_ms": stat.total_processing_time_ms,
                "errors_count": stat.errors_count
            }
            for stat in usage_stats
        ],
        "export_timestamp": datetime.utcnow().isoformat()
    }
    
    return export_data