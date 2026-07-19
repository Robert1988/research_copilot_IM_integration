"""
用户订阅计划和数据附加项配置文件
包含所有订阅计划、数据包的详细配置信息
"""

from typing import Dict, List
from datetime import timedelta, datetime, date
import calendar
from models import SubscriptionPlanDetails, DataAddonDetails, SubscriptionPlanType, DataAddonType

# 计费周期配置
class BillingCycle:
    """计费周期配置"""
    MONTHLY = "monthly"
    YEARLY = "yearly"
    WEEKLY = "weekly"
    
    # PayPal 计费周期配置
    PAYPAL_FREQUENCY = {
        MONTHLY: {"interval_unit": "MONTH", "interval_count": 1},
        YEARLY: {"interval_unit": "YEAR", "interval_count": 1},
        WEEKLY: {"interval_unit": "WEEK", "interval_count": 1}
    }
    
    # 计费周期描述
    CYCLE_DESCRIPTIONS = {
        MONTHLY: "Monthly billing on the same day each month",
        YEARLY: "Yearly billing on the same date each year",
        WEEKLY: "Weekly billing on the same day each week"
    }

# 订阅计划配置
SUBSCRIPTION_PLANS_CONFIG = {
    SubscriptionPlanType.BASE: {
        "plan_details": SubscriptionPlanDetails(
            plan_type=SubscriptionPlanType.BASE,
            price=3.9,
            currency="USD",
            monthly_credits=40,
            description="Base subscription plan - 40 monthly AI generated messages"
        ),
        "billing_cycle": BillingCycle.MONTHLY,
        "billing_frequency": BillingCycle.PAYPAL_FREQUENCY[BillingCycle.MONTHLY],  # PayPal格式
        "trial_period_days": 0,  # 无试用期
        "setup_fee": 0.0,  # 无设置费
        "cancellation_policy": "cancel_anytime",  # 随时取消
        "auto_renewal": True,  # 自动续费
        "features": [
            "40 monthly AI generated messages"
        ],
        "limitations": [
            "Base features only"
        ],
        "paypal_plan_name": "AlignSpires Base Plan",
        "paypal_plan_description": "Base subscription - 40 monthly AI generated messages",
        "paypal_product_category": "SOFTWARE"
    },
    SubscriptionPlanType.PRO: {
        "plan_details": SubscriptionPlanDetails(
            plan_type=SubscriptionPlanType.PRO,
            price=19.9,
            currency="USD",
            monthly_credits=200,
            description="Pro subscription plan - 200 monthly AI generated messages"
        ),
        "billing_cycle": BillingCycle.MONTHLY,
        "billing_frequency": BillingCycle.PAYPAL_FREQUENCY[BillingCycle.MONTHLY],  # PayPal格式
        "trial_period_days": 0,  # 无试用期
        "setup_fee": 0.0,  # 无设置费
        "cancellation_policy": "cancel_anytime",  # 随时取消
        "auto_renewal": True,  # 自动续费``
        "features": [
            "200 monthly AI generated messages",
            "Advanced AI analysis",
        ],
        "limitations": [],
        "paypal_plan_name": "AlignSpires Pro Plan",
        "paypal_plan_description": "Monthly pro subscription with 200 monthly AI generated messages",
        "paypal_product_category": "SOFTWARE"
    }
}

# 数据附加项配置
DATA_ADDONS_CONFIG = {
    DataAddonType.CREDITS_100: {
        "addon_details": DataAddonDetails(
            addon_type=DataAddonType.CREDITS_100,
            price=10.0,
            currency="USD",
            credits=100,
            description="100 additional credits data add-on"
        ),
        "validity_days": 90,  # 90天有效期
        "stackable": True,  # 可叠加购买
        "features": [
            "100 additional credits",
            "90 days validity",
        ],
        "paypal_product_name": "AlignSpires 100 Credits Add-on",
        "paypal_product_description": "100 additional credits with 90 days validity",
        "paypal_product_category": "DIGITAL_GOODS"
    },
    DataAddonType.CREDITS_300: {
        "addon_details": DataAddonDetails(
            addon_type=DataAddonType.CREDITS_300,
            price=30.0,
            currency="USD",
            credits=300,
            description="300 additional credits data add-on"
        ),
        "validity_days": 90,  # 90天有效期
        "stackable": True,  # 可叠加购买
        "features": [
            "300 additional credits",
            "90 days validity",
        ],
        "paypal_product_name": "AlignSpires 300 Credits Add-on",
        "paypal_product_description": "300 additional credits with 90 days validity",
        "paypal_product_category": "DIGITAL_GOODS"
    }
}

# 全局配置
GLOBAL_CONFIG = {
    "default_currency": "USD",
    "upgrade_proration": True,  # 升级时按比例计费
    "downgrade_policy": "end_of_cycle",  # 降级在周期结束时生效
}

# PayPal配置
PAYPAL_CONFIG = {
    "webhook_events": [
        "BILLING.SUBSCRIPTION.ACTIVATED",
        "BILLING.SUBSCRIPTION.CANCELLED", 
        "BILLING.SUBSCRIPTION.SUSPENDED",
        "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
        "PAYMENT.CAPTURE.COMPLETED",
        "PAYMENT.CAPTURE.DENIED"
    ],
    "return_url_template": "{base_url}/slack/payment/success?order_id={order_id}",
    "cancel_url_template": "{base_url}/slack/payment/cancel?order_id={order_id}",
    "subscription_start_delay_minutes": 1,  # 订阅开始延迟1分钟
}

# 便捷访问函数
def get_subscription_plans() -> Dict[SubscriptionPlanType, SubscriptionPlanDetails]:
    """获取所有订阅计划的详情"""
    return {
        plan_type: config["plan_details"] 
        for plan_type, config in SUBSCRIPTION_PLANS_CONFIG.items()
    }

def get_data_addons() -> Dict[DataAddonType, DataAddonDetails]:
    """获取所有数据附加项的详情"""
    return {
        addon_type: config["addon_details"]
        for addon_type, config in DATA_ADDONS_CONFIG.items()
    }

def get_plan_config(plan_type: SubscriptionPlanType) -> Dict:
    """获取指定订阅计划的完整配置"""
    return SUBSCRIPTION_PLANS_CONFIG.get(plan_type, {})

def get_addon_config(addon_type: DataAddonType) -> Dict:
    """获取指定数据附加项的完整配置"""
    return DATA_ADDONS_CONFIG.get(addon_type, {})

def get_billing_frequency(plan_type: SubscriptionPlanType) -> Dict:
    """获取PayPal计费频率配置"""
    config = SUBSCRIPTION_PLANS_CONFIG.get(plan_type, {})
    return config.get("billing_frequency", {"interval_unit": "MONTH", "interval_count": 1})

def get_addon_validity_days(addon_type: DataAddonType) -> int:
    """获取指定数据附加项的有效期天数"""
    config = DATA_ADDONS_CONFIG.get(addon_type, {})
    return config.get("validity_days", 90)

def calculate_next_billing_date(start_date: datetime, billing_cycle: str = BillingCycle.MONTHLY) -> datetime:
    """
    计算下一个计费日期（自然月计费）
    
    Args:
        start_date: 订阅开始日期
        billing_cycle: 计费周期
    
    Returns:
        下一个计费日期
    
    Examples:
        - 1月31日订阅 -> 2月28日计费（2月没有31日）
        - 1月31日订阅 -> 3月31日计费（3月有31日）
        - 1月30日订阅 -> 2月28日计费（2月没有30日）
    """
    if billing_cycle == BillingCycle.MONTHLY:
        # 获取下个月
        if start_date.month == 12:
            next_year = start_date.year + 1
            next_month = 1
        else:
            next_year = start_date.year
            next_month = start_date.month + 1
        
        # 获取下个月的最后一天
        _, last_day_of_next_month = calendar.monthrange(next_year, next_month)
        
        # 如果原始日期超过下个月的最后一天，则使用下个月的最后一天
        billing_day = min(start_date.day, last_day_of_next_month)
        
        return datetime(
            year=next_year,
            month=next_month,
            day=billing_day,
            hour=start_date.hour,
            minute=start_date.minute,
            second=start_date.second,
            microsecond=start_date.microsecond,
            tzinfo=start_date.tzinfo
        )
    
    elif billing_cycle == BillingCycle.YEARLY:
        # 年度计费：同一天，下一年
        next_year = start_date.year + 1
        
        # 处理闰年2月29日的情况
        if start_date.month == 2 and start_date.day == 29:
            # 如果下一年不是闰年，则使用2月28日
            if not calendar.isleap(next_year):
                return start_date.replace(year=next_year, day=28)
        
        return start_date.replace(year=next_year)
    
    elif billing_cycle == BillingCycle.WEEKLY:
        # 周度计费：7天后
        return start_date + timedelta(days=7)
    
    else:
        raise ValueError(f"Unsupported billing cycle: {billing_cycle}")

def calculate_current_billing_period_end(start_date: datetime, current_date: datetime, billing_cycle: str = BillingCycle.MONTHLY) -> datetime:
    """
    计算当前计费周期的结束日期
    
    Args:
        start_date: 订阅开始日期
        current_date: 当前日期（如果为None则使用当前时间）
        billing_cycle: 计费周期
    
    Returns:
        当前计费周期的结束日期
    
    Examples:
        - 订阅开始：2024-01-15，当前：2024-03-10 → 返回 2024-03-15（当前计费周期结束）
        - 订阅开始：2024-01-15，当前：2024-01-20 → 返回 2024-02-15（当前计费周期结束）
        - 订阅开始：2024-01-31，当前：2024-02-10 → 返回 2024-02-29（当前计费周期结束，2月没有31日）
    """
    if current_date is None:
        current_date = datetime.now(start_date.tzinfo if start_date.tzinfo else None)
    
    if billing_cycle == BillingCycle.MONTHLY:
        # 从订阅开始日期开始，逐月计算，找到包含当前日期的计费周期
        period_start = start_date
        
        while True:
            # 计算这个周期的结束日期
            if period_start.month == 12:
                next_year = period_start.year + 1
                next_month = 1
            else:
                next_year = period_start.year
                next_month = period_start.month + 1
            
            # 获取下个月的最后一天
            _, last_day_of_next_month = calendar.monthrange(next_year, next_month)
            
            # 如果原始日期超过下个月的最后一天，则使用下个月的最后一天
            billing_day = min(start_date.day, last_day_of_next_month)
            
            period_end = datetime(
                year=next_year,
                month=next_month,
                day=billing_day,
                hour=start_date.hour,
                minute=start_date.minute,
                second=start_date.second,
                microsecond=start_date.microsecond,
                tzinfo=start_date.tzinfo
            )
            
            # 如果当前日期在这个周期内，返回周期结束日期
            if period_start <= current_date < period_end:
                return period_end
            
            # 移动到下一个周期
            period_start = period_end
    
    elif billing_cycle == BillingCycle.YEARLY:
        # 年度计费
        period_start = start_date
        
        while True:
            # 计算这个周期的结束日期（下一年同一天）
            next_year = period_start.year + 1
            
            # 处理闰年2月29日的情况
            if period_start.month == 2 and period_start.day == 29:
                if not calendar.isleap(next_year):
                    period_end = period_start.replace(year=next_year, day=28)
                else:
                    period_end = period_start.replace(year=next_year)
            else:
                period_end = period_start.replace(year=next_year)
            
            # 如果当前日期在这个周期内，返回周期结束日期
            if period_start <= current_date < period_end:
                return period_end
            
            # 移动到下一个周期
            period_start = period_end
    
    elif billing_cycle == BillingCycle.WEEKLY:
        # 周度计费
        # 计算从开始日期到当前日期经过了多少个完整的周
        days_diff = (current_date.date() - start_date.date()).days
        weeks_passed = days_diff // 7
        
        # 计算当前周期的结束日期
        current_period_end = start_date + timedelta(days=(weeks_passed + 1) * 7)
        return current_period_end
    
    else:
        raise ValueError(f"Unsupported billing cycle: {billing_cycle}")

def calculate_subscription_end_date(start_date: datetime, billing_cycle: str = BillingCycle.MONTHLY, cycles: int = 1) -> datetime:
    """
    计算订阅结束日期
    
    Args:
        start_date: 订阅开始日期
        billing_cycle: 计费周期
        cycles: 计费周期数
    
    Returns:
        订阅结束日期
    """
    current_date = start_date
    
    for _ in range(cycles):
        current_date = calculate_next_billing_date(current_date, billing_cycle)
    
    return current_date

# 功能积分消耗配置
FEATURE_CREDIT_COSTS = {
    "pdf_processing": 1,  # PDF处理消耗1个积分
    "chat_message": 1,    # 聊天消息消耗1个积分
    "code_generation": 4, # 代码生成消耗2个积分
    "image_analysis": 1,  # 图片分析消耗1个积分
}

def get_feature_credit_cost(feature_name: str) -> int:
    """
    获取指定功能的积分消耗量
    
    Args:
        feature_name: 功能名称
    
    Returns:
        积分消耗量，如果功能不存在则返回1
    """
    return FEATURE_CREDIT_COSTS.get(feature_name, 1)


