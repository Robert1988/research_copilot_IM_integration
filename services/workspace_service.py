from typing import List, Optional, Dict, Any
from datetime import datetime
from models import SlackWorkspace
from services.database_service import db_service

class WorkspaceService:
    """工作区管理服务"""
    
    async def add_workspace(self, workspace_data: Dict[str, Any]) -> SlackWorkspace:
        """添加新的工作区配置"""
        return await db_service.create_workspace(workspace_data)
    
    async def get_workspace(self, team_id: str) -> Optional[SlackWorkspace]:
        """获取指定工作区配置"""
        return await db_service.get_workspace_by_team_id(team_id)
    
    async def get_all_workspaces(self) -> List[SlackWorkspace]:
        """获取所有工作区配置"""
        return await db_service.get_all_workspaces()
    
    async def get_active_workspaces(self) -> List[SlackWorkspace]:
        """获取所有活跃的工作区配置"""
        all_workspaces = await self.get_all_workspaces()
        return [ws for ws in all_workspaces if ws.is_active]
    
    async def update_workspace(self, team_id: str, update_data: Dict[str, Any]) -> Optional[SlackWorkspace]:
        """更新工作区配置"""
        return await db_service.update_workspace(team_id, update_data)
    
    async def remove_workspace(self, team_id: str) -> bool:
        """移除工作区配置（软删除）"""
        return await db_service.deactivate_workspace(team_id)
    
    async def workspace_exists(self, team_id: str) -> bool:
        """检查工作区是否存在"""
        workspace = await self.get_workspace(team_id)
        return workspace is not None and workspace.is_active

# 创建全局实例
workspace_service = WorkspaceService()