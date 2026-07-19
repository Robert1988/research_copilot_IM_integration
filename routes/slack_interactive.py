"""
Slack Interactive Message Routes
Handles button clicks, menu selections, and other interactive elements
"""

import json
import logging
from urllib.parse import parse_qs
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from services.slack_interactive_service import slack_interactive_service
from config import settings
import hmac
import hashlib
import time

logger = logging.getLogger(__name__)

router = APIRouter()

def verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify Slack request signature"""
    try:
        # Create the signature base string
        sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
        
        # Create the expected signature
        expected_signature = 'v0=' + hmac.new(
            settings.SLACK_SIGNING_SECRET.encode(),
            sig_basestring.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures
        return hmac.compare_digest(expected_signature, signature)
    except Exception as e:
        logger.error(f"Error verifying Slack signature: {str(e)}")
        return False

@router.post("/interactive")
async def handle_interactive_message(request: Request):
    """Handle Slack interactive message events (button clicks, etc.)"""
    try:
        # Get request body and headers
        body = await request.body()
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")
        
        # Verify timestamp (prevent replay attacks)
        current_time = int(time.time())
        if abs(current_time - int(timestamp)) > 300:  # 5 minutes
            logger.warning("Slack request timestamp too old")
            raise HTTPException(status_code=400, detail="Request timestamp too old")
        
        # Verify Slack signature
        if not verify_slack_signature(body, timestamp, signature):
            logger.warning("Invalid Slack signature")
            raise HTTPException(status_code=400, detail="Invalid signature")
        
        # Parse the form data
        form_data = parse_qs(body.decode('utf-8'))
        payload_str = form_data.get('payload', [''])[0]
        
        if not payload_str:
            raise HTTPException(status_code=400, detail="No payload found")
        
        # Parse JSON payload
        payload = json.loads(payload_str)
        
        logger.info(f"Received interactive message: {payload.get('type', 'unknown')}")
        logger.info(f"Full payload: {json.dumps(payload, indent=2)}")
        
        # Handle different types of interactions
        interaction_type = payload.get("type")
        
        if interaction_type == "block_actions":
            # Handle button clicks and other block actions
            response = await slack_interactive_service.handle_button_interaction(payload)
            logger.info(f"Returning response to Slack: {response}")
            return JSONResponse(content=response)
        
        elif interaction_type == "message_action":
            # Handle message actions (right-click menu items)
            return JSONResponse(content={
                "response_type": "ephemeral",
                "text": "消息操作功能正在开发中..."
            })
        
        elif interaction_type == "shortcut":
            # Handle global shortcuts
            return JSONResponse(content={
                "response_type": "ephemeral",
                "text": "快捷方式功能正在开发中..."
            })
        
        else:
            logger.warning(f"Unknown interaction type: {interaction_type}")
            return JSONResponse(content={
                "response_type": "ephemeral",
                "text": "未知的交互类型"
            })
    
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON payload: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    except Exception as e:
        logger.error(f"Error handling interactive message: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/options")
async def handle_options_request(request: Request):
    """Handle Slack options requests for dynamic menus"""
    try:
        # Get request body and headers
        body = await request.body()
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")
        
        # Verify Slack signature
        if not verify_slack_signature(body, timestamp, signature):
            logger.warning("Invalid Slack signature for options request")
            raise HTTPException(status_code=400, detail="Invalid signature")
        
        # Parse the form data
        form_data = parse_qs(body.decode('utf-8'))
        payload_str = form_data.get('payload', [''])[0]
        payload = json.loads(payload_str)
        
        # Handle options loading (for dynamic select menus)
        action_id = payload.get("action_id", "")
        
        if action_id == "select_subscription_plan":
            # Return subscription plan options
            return JSONResponse(content={
                "options": [
                    {
                        "text": {"type": "plain_text", "text": "⭐ 基础计划 - $9.99/月"},
                        "value": "base"
                    },
                    {
                        "text": {"type": "plain_text", "text": "🚀 高级计划 - $19.99/月"},
                        "value": "pro"
                    }
                ]
            })
        
        return JSONResponse(content={"options": []})
    
    except Exception as e:
        logger.error(f"Error handling options request: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")