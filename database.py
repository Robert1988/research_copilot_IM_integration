from motor.motor_asyncio import AsyncIOMotorClient
from config import settings

class Database:
    client: AsyncIOMotorClient = None
    database = None

db = Database()

async def get_database():
    return db.database

async def init_database():
    """Initialize database connection"""
    db.client = AsyncIOMotorClient(settings.MONGODB_URL)
    db.database = db.client[settings.MONGODB_DB_NAME]
    
    # Create indexes
    await create_indexes()
    
    print(f"Connected to MongoDB: {settings.MONGODB_DB_NAME}")

async def close_database():
    """Close database connection"""
    if db.client:
        try:
            # 关闭所有连接
            db.client.close()
            print("MongoDB connections closed successfully")
        except Exception as e:
            print(f"Error closing MongoDB connections: {e}")
        finally:
            db.client = None
            db.database = None

async def create_indexes():
    """Create database indexes for better performance"""
    database = db.database
    
    try:
        # 删除旧的email唯一索引（如果存在）
        try:
            await database.users.drop_index("email_1")
            print("Dropped old email unique index")
        except Exception as e:
            print(f"No old email index to drop or error dropping: {e}")
        
        # 删除旧的slack_user_id唯一索引（如果存在）
        try:
            await database.users.drop_index("slack_user_id_1")
            print("Dropped old slack_user_id unique index")
        except Exception as e:
            print(f"No old slack_user_id index to drop or error dropping: {e}")
    except Exception as e:
        print(f"Error during index cleanup: {e}")
    
    # User collection indexes
    # 使用复合唯一索引：slack_team_id + slack_user_id 确保在同一团队中用户唯一
    await database.users.create_index([("slack_team_id", 1), ("slack_user_id", 1)], unique=True)
    # email作为普通索引，不要求唯一
    await database.users.create_index("email")
    
    # Subscription collection indexes
    await database.subscriptions.create_index("user_id")
    await database.subscriptions.create_index("status")
    
    # Message log collection indexes
    await database.message_logs.create_index("user_id")
    await database.message_logs.create_index("timestamp")
    await database.message_logs.create_index([("user_id", 1), ("timestamp", -1)])
    
    # Usage stats collection indexes
    await database.usage_stats.create_index("user_id")
    await database.usage_stats.create_index("date")