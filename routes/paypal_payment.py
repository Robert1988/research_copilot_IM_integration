"""
PayPal Payment Processing Routes
Handles payment completion, cancellation, and status updates
"""

import logging
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from services.paypal_handler import PayPalHandler
from services.subscription_service import subscription_service
from services.database_service import db_service
from models import SubscriptionPlan, SubscriptionStatus
from services.slack_service import slack_service
from services.slack_interactive_service import slack_interactive_service

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/paypal/success")
async def handle_payment_success(
    token: str = Query(..., description="PayPal approval token"),
    PayerID: str = Query(None, description="PayPal payer ID"),
    subscription_id: str = Query(None, description="PayPal subscription ID"),
    ba_token: str = Query(None, description="PayPal billing agreement token")
):
    """Handle successful PayPal payment"""
    try:
        logger.info(f"Processing PayPal payment success: token={token}, PayerID={PayerID}, subscription_id={subscription_id}, ba_token={ba_token}")
        
        # Initialize PayPal handler
        paypal_handler = PayPalHandler()
        
        # Check if this is a subscription payment
        if subscription_id:
            # Handle subscription activation
            logger.info(f"Handling subscription activation for subscription_id: {subscription_id}")
            
            # Get subscription details from PayPal to determine the plan type
            try:
                # Get PayPal access token
                access_token = await paypal_handler.get_access_token()
                
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {access_token}'
                }
                
                # Get subscription details from PayPal
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{paypal_handler.base_url}/v1/billing/subscriptions/{subscription_id}",
                        headers=headers
                    ) as response:
                        if response.status == 200:
                            subscription_details = await response.json()
                            logger.info(f"PayPal subscription details: {subscription_details}")
                            
                            # Extract plan information
                            plan_id = subscription_details.get('plan_id', '')
                            
                            # Determine subscription plan type based on plan_id or other details
                            # For now, we'll default to 'base' but this should be improved
                            subscription_plan_type = "base"  # Default
                            
                            # You might want to map plan_id to subscription_plan_type here
                            # based on your PayPal plan configuration
                            
                        else:
                            logger.error(f"Failed to get subscription details from PayPal: {response.status}")
                            subscription_plan_type = "base"  # Default fallback
                            
            except Exception as e:
                logger.error(f"Error getting subscription details: {str(e)}")
                subscription_plan_type = "base"  # Default fallback
            
            # Try to get the original order_doc from database first
            try:
                orders_collection = await paypal_handler._get_orders_collection()
                # Find the order by subscription_id or order_id
                order_doc = await orders_collection.find_one({
                    "$or": [
                        {"order_id": subscription_id},
                        {"paypal_response.id": subscription_id}
                    ]
                })
                
                if order_doc:
                    logger.info(f"Found existing order_doc in database: {order_doc.get('order_id')}")
                    # Use the real user_id from the order_doc
                    real_user_id = order_doc.get("user_id", "system")
                else:
                    logger.warning("No existing order_doc found, creating minimal one")
                    # If no order_doc found, we can't proceed without a valid user_id
                    # This should not happen in normal flow, but we'll handle it gracefully
                    real_user_id = "system"
                    order_doc = {
                        "order_id": subscription_id,
                        "user_id": real_user_id,
                        "subscription_plan_type": subscription_plan_type,
                        "is_subscription": True,
                        "slack_user_id": "system"
                    }
                    
            except Exception as e:
                logger.error(f"Error retrieving order_doc from database: {str(e)}")
                # Create minimal order_doc as fallback
                real_user_id = "system"
                order_doc = {
                    "order_id": subscription_id,
                    "user_id": real_user_id, 
                    "subscription_plan_type": subscription_plan_type,
                    "is_subscription": True,
                    "slack_user_id": "system"
                }
            
            # For subscription, we need to activate it and handle the subscription flow
            # Use the real user_id from the order_doc instead of hardcoded "system"
            activation_result = await paypal_handler._handle_subscription_activation(subscription_id, user_id=real_user_id, order_doc=order_doc)
            
            if activation_result:
                return HTMLResponse(
                    content="""
                    <!DOCTYPE html>
                    <html lang="en">
                        <head>
                            <meta charset="UTF-8">
                            <meta name="viewport" content="width=device-width, initial-scale=1.0">
                            <title>Subscription Activated</title>
                            <style>
                                * { margin: 0; padding: 0; box-sizing: border-box; }
                                body {
                                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                                    min-height: 100vh;
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                    padding: 20px;
                                }
                                .container {
                                    background: white;
                                    border-radius: 20px;
                                    padding: 40px;
                                    text-align: center;
                                    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                                    max-width: 500px;
                                    width: 100%;
                                }
                                .icon {
                                    font-size: 4rem;
                                    margin-bottom: 20px;
                                    animation: bounce 2s infinite;
                                }
                                @keyframes bounce {
                                    0%, 20%, 50%, 80%, 100% { transform: translateY(0); }
                                    40% { transform: translateY(-10px); }
                                    60% { transform: translateY(-5px); }
                                }
                                h1 {
                                    color: #28a745;
                                    font-size: 2rem;
                                    margin-bottom: 15px;
                                    font-weight: 600;
                                }
                                p {
                                    color: #6c757d;
                                    font-size: 1.1rem;
                                    line-height: 1.6;
                                    margin-bottom: 30px;
                                }
                                .btn {
                                    background: linear-gradient(45deg, #28a745, #20c997);
                                    color: white;
                                    border: none;
                                    padding: 15px 30px;
                                    border-radius: 50px;
                                    font-size: 1rem;
                                    font-weight: 500;
                                    cursor: pointer;
                                    transition: all 0.3s ease;
                                    text-decoration: none;
                                    display: inline-block;
                                }
                                .btn:hover {
                                    transform: translateY(-2px);
                                    box-shadow: 0 10px 20px rgba(40, 167, 69, 0.3);
                                }
                            </style>
                        </head>
                        <body>
                            <div class="container">
                                <div class="icon">🎉</div>
                                <h1>Subscription Activated!</h1>
                                <p>Your subscription has been successfully activated. You will receive a confirmation message shortly.</p>
                                <button class="btn" onclick="window.close()">Close Window</button>
                            </div>
                        </body>
                    </html>
                    """,
                    status_code=200
                )
            else:
                return HTMLResponse(
                    content="""
                    <!DOCTYPE html>
                    <html lang="en">
                        <head>
                            <meta charset="UTF-8">
                            <meta name="viewport" content="width=device-width, initial-scale=1.0">
                            <title>Activation Failed</title>
                            <style>
                                * { margin: 0; padding: 0; box-sizing: border-box; }
                                body {
                                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                                    background: linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%);
                                    min-height: 100vh;
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                    padding: 20px;
                                }
                                .container {
                                    background: white;
                                    border-radius: 20px;
                                    padding: 40px;
                                    text-align: center;
                                    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                                    max-width: 500px;
                                    width: 100%;
                                }
                                .icon {
                                    font-size: 4rem;
                                    margin-bottom: 20px;
                                    animation: shake 0.5s ease-in-out;
                                }
                                @keyframes shake {
                                    0%, 100% { transform: translateX(0); }
                                    25% { transform: translateX(-5px); }
                                    75% { transform: translateX(5px); }
                                }
                                h1 {
                                    color: #dc3545;
                                    font-size: 2rem;
                                    margin-bottom: 15px;
                                    font-weight: 600;
                                }
                                p {
                                    color: #6c757d;
                                    font-size: 1.1rem;
                                    line-height: 1.6;
                                    margin-bottom: 30px;
                                }
                                .btn {
                                    background: linear-gradient(45deg, #dc3545, #c82333);
                                    color: white;
                                    border: none;
                                    padding: 15px 30px;
                                    border-radius: 50px;
                                    font-size: 1rem;
                                    font-weight: 500;
                                    cursor: pointer;
                                    transition: all 0.3s ease;
                                    text-decoration: none;
                                    display: inline-block;
                                }
                                .btn:hover {
                                    transform: translateY(-2px);
                                    box-shadow: 0 10px 20px rgba(220, 53, 69, 0.3);
                                }
                            </style>
                        </head>
                        <body>
                            <div class="container">
                                <div class="icon">❌</div>
                                <h1>Activation Failed</h1>
                                <p>There was an issue during the subscription activation process. Please contact customer support.</p>
                                <button class="btn" onclick="window.close()">Close Window</button>
                            </div>
                        </body>
                    </html>
                    """,
                    status_code=400
                )
        
        # Handle regular order capture (non-subscription)
        capture_result = await paypal_handler.capture_order(token, user_id="system")
        
        if capture_result.success:
            # Get order details from the capture result
            order_details = capture_result.order_details
            if not order_details:
                logger.error("No order details found in capture result")
                return HTMLResponse(
                    content="""
                    <!DOCTYPE html>
                    <html lang="en">
                        <head>
                            <meta charset="UTF-8">
                            <meta name="viewport" content="width=device-width, initial-scale=1.0">
                            <title>Processing Failed</title>
                            <style>
                                * { margin: 0; padding: 0; box-sizing: border-box; }
                                body {
                                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                                    background: linear-gradient(135deg, #ffc107 0%, #fd7e14 100%);
                                    min-height: 100vh;
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                    padding: 20px;
                                }
                                .container {
                                    background: white;
                                    border-radius: 20px;
                                    padding: 40px;
                                    text-align: center;
                                    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                                    max-width: 500px;
                                    width: 100%;
                                }
                                .icon {
                                    font-size: 4rem;
                                    margin-bottom: 20px;
                                }
                                h1 {
                                    color: #dc3545;
                                    font-size: 2rem;
                                    margin-bottom: 15px;
                                    font-weight: 600;
                                }
                                p {
                                    color: #6c757d;
                                    font-size: 1.1rem;
                                    line-height: 1.6;
                                    margin-bottom: 30px;
                                }
                                .btn {
                                    background: linear-gradient(45deg, #ffc107, #fd7e14);
                                    color: white;
                                    border: none;
                                    padding: 15px 30px;
                                    border-radius: 50px;
                                    font-size: 1rem;
                                    font-weight: 500;
                                    cursor: pointer;
                                    transition: all 0.3s ease;
                                    text-decoration: none;
                                    display: inline-block;
                                }
                                .btn:hover {
                                    transform: translateY(-2px);
                                    box-shadow: 0 10px 20px rgba(255, 193, 7, 0.3);
                                }
                            </style>
                        </head>
                        <body>
                            <div class="container">
                                <div class="icon">❌</div>
                                <h1>Processing Failed</h1>
                                <p>Unable to find order details. Please contact customer support.</p>
                                <button class="btn" onclick="window.close()">Close Window</button>
                            </div>
                        </body>
                    </html>
                    """,
                    status_code=400
                )
            
            user_id = order_details.get("user_id")
            slack_user_id = order_details.get("slack_user_id")
            plan = order_details.get("plan")
            
            # Update user subscription
            subscription_plan = SubscriptionPlan.BASE if plan == "base" else SubscriptionPlan.PRO
            
            result = await subscription_service.create_or_update_subscription(
                user_id=user_id,
                plan=subscription_plan,
                payment_method="paypal",
                external_subscription_id=capture_result.subscription_id
            )
            
            if result["success"]:
                # Send success message to Slack
                try:
                    blocks = slack_interactive_service.create_payment_success_blocks(plan)
                    await slack_service.send_direct_message(
                        user_id=slack_user_id,
                        blocks=blocks,
                        text=f"🎉 Successfully subscribed to {plan.title()} plan!"
                    )
                except Exception as e:
                    logger.error(f"Error sending success message to Slack: {str(e)}")
                
                # Return success page
                return HTMLResponse(
                    content=f"""
                    <!DOCTYPE html>
                    <html lang="en">
                        <head>
                            <meta charset="UTF-8">
                            <meta name="viewport" content="width=device-width, initial-scale=1.0">
                            <title>Payment Successful</title>
                            <style>
                                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                                body {{
                                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                                    min-height: 100vh;
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                    padding: 20px;
                                }}
                                .container {{
                                    background: white;
                                    border-radius: 20px;
                                    padding: 40px;
                                    text-align: center;
                                    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                                    max-width: 500px;
                                    width: 100%;
                                }}
                                .icon {{
                                    font-size: 4rem;
                                    margin-bottom: 20px;
                                    animation: bounce 2s infinite;
                                }}
                                @keyframes bounce {{
                                    0%, 20%, 50%, 80%, 100% {{ transform: translateY(0); }}
                                    40% {{ transform: translateY(-10px); }}
                                    60% {{ transform: translateY(-5px); }}
                                }}
                                h1 {{
                                    color: #28a745;
                                    font-size: 2rem;
                                    margin-bottom: 10px;
                                    font-weight: 600;
                                }}
                                h2 {{
                                    color: #495057;
                                    font-size: 1.3rem;
                                    margin-bottom: 15px;
                                    font-weight: 500;
                                }}
                                p {{
                                    color: #6c757d;
                                    font-size: 1.1rem;
                                    line-height: 1.6;
                                    margin-bottom: 30px;
                                }}
                                .plan-badge {{
                                    background: linear-gradient(45deg, #667eea, #764ba2);
                                    color: white;
                                    padding: 8px 16px;
                                    border-radius: 20px;
                                    font-weight: 600;
                                    text-transform: uppercase;
                                    font-size: 0.9rem;
                                    margin: 0 5px;
                                }}
                                .btn {{
                                    background: linear-gradient(45deg, #28a745, #20c997);
                                    color: white;
                                    border: none;
                                    padding: 15px 30px;
                                    border-radius: 50px;
                                    font-size: 1rem;
                                    font-weight: 500;
                                    cursor: pointer;
                                    transition: all 0.3s ease;
                                    text-decoration: none;
                                    display: inline-block;
                                }}
                                .btn:hover {{
                                    transform: translateY(-2px);
                                    box-shadow: 0 10px 20px rgba(40, 167, 69, 0.3);
                                }}
                            </style>
                        </head>
                        <body>
                            <div class="container">
                                <div class="icon">✅</div>
                                <h1>Payment Successful!</h1>
                                <h2>🎉 Congratulations! You have successfully subscribed to the <span class="plan-badge">{plan.title()}</span> plan</h2>
                                <p>Your subscription has been activated and you can now enjoy all features in Slack!</p>
                                <p>Return to Slack to start using it!</p>
                                <p><a href="javascript:window.close()">Close Window</a></p>
                            </div>
                        </body>
                    </html>
                    """
                )
            else:
                logger.error("Failed to update user subscription after successful payment")
                return HTMLResponse(
                    content="""
                    <!DOCTYPE html>
                    <html lang="en">
                        <head>
                            <meta charset="UTF-8">
                            <meta name="viewport" content="width=device-width, initial-scale=1.0">
                            <title>Subscription Issue</title>
                            <style>
                                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                                body {{
                                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                                    background: linear-gradient(135deg, #ffc107 0%, #fd7e14 100%);
                                    min-height: 100vh;
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                    padding: 20px;
                                }}
                                .container {{
                                    background: white;
                                    border-radius: 20px;
                                    padding: 40px;
                                    text-align: center;
                                    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                                    max-width: 500px;
                                    width: 100%;
                                }}
                                .icon {{
                                    font-size: 4rem;
                                    margin-bottom: 20px;
                                }}
                                h1 {{
                                    color: #fd7e14;
                                    font-size: 1.8rem;
                                    margin-bottom: 15px;
                                    font-weight: 600;
                                }}
                                p {{
                                    color: #6c757d;
                                    font-size: 1.1rem;
                                    line-height: 1.6;
                                    margin-bottom: 30px;
                                }}
                                .btn {{
                                    background: linear-gradient(45deg, #ffc107, #fd7e14);
                                    color: white;
                                    border: none;
                                    padding: 15px 30px;
                                    border-radius: 50px;
                                    font-size: 1rem;
                                    font-weight: 500;
                                    cursor: pointer;
                                    transition: all 0.3s ease;
                                    text-decoration: none;
                                    display: inline-block;
                                }}
                                .btn:hover {{
                                    transform: translateY(-2px);
                                    box-shadow: 0 10px 20px rgba(255, 193, 7, 0.3);
                                }}
                            </style>
                        </head>
                        <body>
                            <div class="container">
                                <div class="icon">⚠️</div>
                                <h1>Payment Successful, but Subscription Activation Failed</h1>
                                <p>Your payment was successful, but there was an issue activating your subscription. Please contact customer support.</p>
                                <button class="btn" onclick="window.close()">Close Window</button>
                            </div>
                        </body>
                    </html>
                    """,
                    status_code=500
                )
        else:
            error_message = capture_result.error_message or "Payment processing failed"
            logger.error(f"Payment capture failed: {error_message}")
            
            return HTMLResponse(
                content=f"""
                <!DOCTYPE html>
                <html lang="en">
                    <head>
                        <meta charset="UTF-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1.0">
                        <title>Payment Failed</title>
                        <style>
                            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                            body {{
                                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                                background: linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%);
                                min-height: 100vh;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                padding: 20px;
                            }}
                            .container {{
                                background: white;
                                border-radius: 20px;
                                padding: 40px;
                                text-align: center;
                                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                                max-width: 500px;
                                width: 100%;
                            }}
                            .icon {{
                                font-size: 4rem;
                                margin-bottom: 20px;
                                animation: shake 0.5s ease-in-out;
                            }}
                            @keyframes shake {{
                                0%, 100% {{ transform: translateX(0); }}
                                25% {{ transform: translateX(-5px); }}
                                75% {{ transform: translateX(5px); }}
                            }}
                            h1 {{
                                color: #dc3545;
                                font-size: 2rem;
                                margin-bottom: 15px;
                                font-weight: 600;
                            }}
                            p {{
                                color: #6c757d;
                                font-size: 1.1rem;
                                line-height: 1.6;
                                margin-bottom: 30px;
                            }}
                            .error-msg {{
                                background: #f8f9fa;
                                border-left: 4px solid #dc3545;
                                padding: 15px;
                                margin: 20px 0;
                                border-radius: 5px;
                                font-family: monospace;
                                color: #495057;
                                text-align: left;
                            }}
                            .btn {{
                                background: linear-gradient(45deg, #dc3545, #c82333);
                                color: white;
                                border: none;
                                padding: 15px 30px;
                                border-radius: 50px;
                                font-size: 1rem;
                                font-weight: 500;
                                cursor: pointer;
                                transition: all 0.3s ease;
                                text-decoration: none;
                                display: inline-block;
                            }}
                            .btn:hover {{
                                transform: translateY(-2px);
                                box-shadow: 0 10px 20px rgba(220, 53, 69, 0.3);
                            }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="icon">❌</div>
                            <h1>Payment Failed</h1>
                            <p>There was an issue processing your payment:</p>
                            <div class="error-msg">{error_message}</div>
                            <p>Please try again or contact customer support.</p>
                            <button class="btn" onclick="window.close()">Close Window</button>
                        </div>
                    </body>
                </html>
                """,
                status_code=400
            )
    
    except Exception as e:
        logger.error(f"Error handling payment success: {str(e)}")
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>System Error</title>
                    <style>
                        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                        body {{
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                            background: linear-gradient(135deg, #6c757d 0%, #495057 100%);
                            min-height: 100vh;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            padding: 20px;
                        }}
                        .container {{
                            background: white;
                            border-radius: 20px;
                            padding: 40px;
                            text-align: center;
                            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                            max-width: 500px;
                            width: 100%;
                        }}
                        .icon {{
                            font-size: 4rem;
                            margin-bottom: 20px;
                        }}
                        h1 {{
                            color: #6c757d;
                            font-size: 2rem;
                            margin-bottom: 15px;
                            font-weight: 600;
                        }}
                        p {{
                            color: #6c757d;
                            font-size: 1.1rem;
                            line-height: 1.6;
                            margin-bottom: 30px;
                        }}
                        .error-msg {{
                            background: #f8f9fa;
                            border-left: 4px solid #6c757d;
                            padding: 15px;
                            margin: 20px 0;
                            border-radius: 5px;
                            font-family: monospace;
                            color: #495057;
                            text-align: left;
                        }}
                        .btn {{
                            background: linear-gradient(45deg, #6c757d, #495057);
                            color: white;
                            border: none;
                            padding: 15px 30px;
                            border-radius: 50px;
                            font-size: 1rem;
                            font-weight: 500;
                            cursor: pointer;
                            transition: all 0.3s ease;
                            text-decoration: none;
                            display: inline-block;
                        }}
                        .btn:hover {{
                            transform: translateY(-2px);
                            box-shadow: 0 10px 20px rgba(108, 117, 125, 0.3);
                        }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="icon">❌</div>
                        <h1>Error Processing Payment</h1>
                        <div class="error-msg">System error: {str(e)}</div>
                        <p>Please contact customer support.</p>
                        <button class="btn" onclick="window.close()">Close Window</button>
                    </div>
                </body>
            </html>
            """,
            status_code=500
        )

@router.get("/paypal/cancel")
async def handle_payment_cancel(token: str = Query(..., description="PayPal token")):
    """Handle cancelled PayPal payment"""
    try:
        logger.info(f"PayPal payment cancelled: token={token}")
        
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Payment Cancelled</title>
                    <style>
                        * { margin: 0; padding: 0; box-sizing: border-box; }
                        body {
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                            background: linear-gradient(135deg, #6c757d 0%, #495057 100%);
                            min-height: 100vh;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            padding: 20px;
                        }
                        .container {
                            background: white;
                            border-radius: 20px;
                            padding: 40px;
                            text-align: center;
                            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                            max-width: 500px;
                            width: 100%;
                        }
                        .icon {
                            font-size: 4rem;
                            margin-bottom: 20px;
                            animation: fadeIn 1s ease-in;
                        }
                        @keyframes fadeIn {
                            from { opacity: 0; transform: scale(0.5); }
                            to { opacity: 1; transform: scale(1); }
                        }
                        h1 {
                            color: #6c757d;
                            font-size: 2rem;
                            margin-bottom: 15px;
                            font-weight: 600;
                        }
                        p {
                            color: #6c757d;
                            font-size: 1.1rem;
                            line-height: 1.6;
                            margin-bottom: 30px;
                        }
                        .btn {
                            background: linear-gradient(45deg, #6c757d, #495057);
                            color: white;
                            border: none;
                            padding: 15px 30px;
                            border-radius: 50px;
                            font-size: 1rem;
                            font-weight: 500;
                            cursor: pointer;
                            transition: all 0.3s ease;
                            text-decoration: none;
                            display: inline-block;
                        }
                        .btn:hover {
                            transform: translateY(-2px);
                            box-shadow: 0 10px 20px rgba(108, 117, 125, 0.3);
                        }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="icon">❌</div>
                        <h1>Payment Cancelled</h1>
                        <p>You have cancelled the payment process.</p>
                        <p>If you wish to continue with your subscription, please return to Slack and start again.</p>
                        <button class="btn" onclick="window.close()">Close Window</button>
                    </div>
                </body>
            </html>
            """
        )
    
    except Exception as e:
        logger.error(f"Error handling payment cancellation: {str(e)}")
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Error</title>
                    <style>
                        * { margin: 0; padding: 0; box-sizing: border-box; }
                        body {
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                            background: linear-gradient(135deg, #6c757d 0%, #495057 100%);
                            min-height: 100vh;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            padding: 20px;
                        }
                        .container {
                            background: white;
                            border-radius: 20px;
                            padding: 40px;
                            text-align: center;
                            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                            max-width: 500px;
                            width: 100%;
                        }
                        .icon {
                            font-size: 4rem;
                            margin-bottom: 20px;
                        }
                        h1 {
                            color: #6c757d;
                            font-size: 1.8rem;
                            margin-bottom: 15px;
                            font-weight: 600;
                        }
                        .btn {
                            background: linear-gradient(45deg, #6c757d, #495057);
                            color: white;
                            border: none;
                            padding: 15px 30px;
                            border-radius: 50px;
                            font-size: 1rem;
                            font-weight: 500;
                            cursor: pointer;
                            transition: all 0.3s ease;
                            text-decoration: none;
                            display: inline-block;
                        }
                        .btn:hover {
                            transform: translateY(-2px);
                            box-shadow: 0 10px 20px rgba(108, 117, 125, 0.3);
                        }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="icon">⚠️</div>
                        <h1>Error Processing Cancellation Request</h1>
                        <button class="btn" onclick="window.close()">Close Window</button>
                    </div>
                </body>
            </html>
            """,
            status_code=500
        )

@router.get("/paypal/status/{order_id}")
async def get_payment_status(order_id: str):
    """Get payment status for an order"""
    try:
        paypal_handler = PayPalHandler()
        status = await paypal_handler.get_order_status(order_id)
        
        return {
            "success": True,
            "order_id": order_id,
            "status": status
        }
    
    except Exception as e:
        logger.error(f"Error getting payment status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))