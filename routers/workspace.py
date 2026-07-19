from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from services.workspace_service import workspace_service
from services.slack_service import slack_service
from models import SlackWorkspace

router = APIRouter()

class WorkspaceCreate(BaseModel):
    team_id: str
    team_name: str
    bot_token: str
    bot_user_id: str
    scope: str
    app_id: str

class WorkspaceUpdate(BaseModel):
    team_name: Optional[str] = None
    bot_token: Optional[str] = None
    bot_user_id: Optional[str] = None
    scope: Optional[str] = None
    is_active: Optional[bool] = None

@router.post("/", response_model=Dict[str, Any])
async def create_workspace(workspace_data: WorkspaceCreate):
    """创建新的工作区配置"""
    try:
        # 检查工作区是否已存在
        existing = await workspace_service.get_workspace(workspace_data.team_id)
        if existing:
            raise HTTPException(status_code=400, detail="工作区已存在")
        
        # 验证Bot Token
        try:
            from slack_sdk import WebClient
            client = WebClient(token=workspace_data.bot_token)
            auth_test = client.auth_test()
            if not auth_test["ok"]:
                raise HTTPException(status_code=400, detail="无效的Bot Token")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Bot Token验证失败: {str(e)}")
        
        # 创建工作区配置
        workspace = await workspace_service.add_workspace(workspace_data.dict())
        
        # 添加到Slack服务
        slack_service.add_workspace_token(workspace.team_id, workspace.bot_token)
        
        return {
            "message": "工作区配置创建成功",
            "workspace": {
                "team_id": workspace.team_id,
                "team_name": workspace.team_name,
                "is_active": workspace.is_active
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建工作区配置失败: {str(e)}")

@router.get("/", response_model=List[Dict[str, Any]])
async def list_workspaces():
    """获取所有工作区配置"""
    try:
        workspaces = await workspace_service.get_all_workspaces()
        return [
            {
                "team_id": ws.team_id,
                "team_name": ws.team_name,
                "bot_user_id": ws.bot_user_id,
                "scope": ws.scope,
                "is_active": ws.is_active,
                "installed_at": ws.installed_at.isoformat() if ws.installed_at else None
            }
            for ws in workspaces
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取工作区列表失败: {str(e)}")

@router.get("/{team_id}", response_model=Dict[str, Any])
async def get_workspace(team_id: str):
    """获取指定工作区配置"""
    try:
        workspace = await workspace_service.get_workspace(team_id)
        if not workspace:
            raise HTTPException(status_code=404, detail="工作区不存在")
        
        return {
            "team_id": workspace.team_id,
            "team_name": workspace.team_name,
            "bot_user_id": workspace.bot_user_id,
            "scope": workspace.scope,
            "is_active": workspace.is_active,
            "installed_at": workspace.installed_at.isoformat() if workspace.installed_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取工作区配置失败: {str(e)}")

@router.put("/{team_id}", response_model=Dict[str, Any])
async def update_workspace(team_id: str, update_data: WorkspaceUpdate):
    """更新工作区配置"""
    try:
        # 检查工作区是否存在
        existing = await workspace_service.get_workspace(team_id)
        if not existing:
            raise HTTPException(status_code=404, detail="工作区不存在")
        
        # 如果更新Bot Token，需要验证
        if update_data.bot_token:
            try:
                from slack_sdk import WebClient
                client = WebClient(token=update_data.bot_token)
                auth_test = client.auth_test()
                if not auth_test["ok"]:
                    raise HTTPException(status_code=400, detail="无效的Bot Token")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Bot Token验证失败: {str(e)}")
        
        # 更新工作区配置
        workspace = await workspace_service.update_workspace(
            team_id, 
            {k: v for k, v in update_data.dict().items() if v is not None}
        )
        
        if not workspace:
            raise HTTPException(status_code=500, detail="更新失败")
        
        # 如果更新了Bot Token，同步到Slack服务
        if update_data.bot_token:
            slack_service.add_workspace_token(team_id, update_data.bot_token)
        
        return {
            "message": "工作区配置更新成功",
            "workspace": {
                "team_id": workspace.team_id,
                "team_name": workspace.team_name,
                "is_active": workspace.is_active
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新工作区配置失败: {str(e)}")

@router.delete("/{team_id}", response_model=Dict[str, str])
async def delete_workspace(team_id: str):
    """删除工作区配置"""
    try:
        # 检查工作区是否存在
        existing = await workspace_service.get_workspace(team_id)
        if not existing:
            raise HTTPException(status_code=404, detail="工作区不存在")
        
        # 软删除工作区
        success = await workspace_service.remove_workspace(team_id)
        if not success:
            raise HTTPException(status_code=500, detail="删除失败")
        
        # 从Slack服务中移除
        if team_id in slack_service.workspace_tokens:
            del slack_service.workspace_tokens[team_id]
        if team_id in slack_service.workspace_clients:
            del slack_service.workspace_clients[team_id]
        
        return {"message": "工作区配置删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除工作区配置失败: {str(e)}")

@router.post("/{team_id}/test", response_model=Dict[str, Any])
async def test_workspace_connection(team_id: str):
    """测试工作区连接"""
    try:
        workspace = await workspace_service.get_workspace(team_id)
        if not workspace:
            raise HTTPException(status_code=404, detail="工作区不存在")
        
        # 测试连接
        client = slack_service.get_client_for_team(team_id)
        if not client:
            raise HTTPException(status_code=400, detail="未找到工作区客户端")
        
        auth_test = client.auth_test()
        if auth_test["ok"]:
            return {
                "status": "success",
                "message": "连接测试成功",
                "team_info": {
                    "team": auth_test.get("team"),
                    "user": auth_test.get("user"),
                    "user_id": auth_test.get("user_id")
                }
            }
        else:
            return {
                "status": "error",
                "message": "连接测试失败",
                "error": auth_test.get("error", "未知错误")
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"连接测试失败: {str(e)}")