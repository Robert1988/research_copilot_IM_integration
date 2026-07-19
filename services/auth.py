import logging
from motor.motor_asyncio import AsyncIOMotorClient
from config import settings

# 数据库连接
client = AsyncIOMotorClient(settings.MONGODB_URL)
db = client[settings.MONGODB_DB_NAME]

def get_db():
    """获取数据库连接"""
    return db