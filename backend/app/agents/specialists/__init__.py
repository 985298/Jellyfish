"""specialists 子包：4 个专业 Agent + create_agent_with_tools 工厂函数。

工具实现在 app.agents.tools（由另一个子代理编写），
本模块只负责按 agent 名称装配工具并创建 agent 实例。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agents.core import Tool
from app.agents.specialists.character_designer import CharacterDesignerAgent
from app.agents.specialists.director import DirectorAgent
from app.agents.specialists.production import ProductionAgent
from app.agents.specialists.storyboard import StoryboardAgent

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

_AGENT_CLASSES = {
    "director": DirectorAgent,
    "character_designer": CharacterDesignerAgent,
    "storyboard": StoryboardAgent,
    "production": ProductionAgent,
}

# Agent -> 可用工具名（设计文档第三章映射表）
_AGENT_TOOL_NAMES: dict[str, list[str]] = {
    "director": [
        "get_chapter_script",
        "check_asset_status",
        "query_assets",
        "query_shots",
        "check_task_status",
    ],
    "character_designer": [
        "get_chapter_script",
        "extract_assets",
        "generate_image",
        "check_asset_status",
        "query_assets",
    ],
    "storyboard": [
        "get_chapter_script",
        "extract_shots",
        "bind_assets",
        "query_shots",
    ],
    "production": [
        "query_shots",
        "generate_frame",
        "generate_video",
        "check_task_status",
    ],
}


def _build_tool_registry() -> dict[str, Tool]:
    """导入工具模块并构建 snake_case name -> Tool 实例的注册表。

    tools/ 目录由另一个子代理实现，此处按设计文档第二章的模块结构导入。
    """
    from app.agents.tools.asset_tools import (
        CheckAssetStatusTool,
        ExtractAssetsTool,
        GenerateImageTool,
        GetChapterScriptTool,
        QueryAssetsTool,
    )
    from app.agents.tools.media_tools import GenerateFrameTool, GenerateVideoTool
    from app.agents.tools.shot_tools import (
        BindAssetsTool,
        ExtractShotsTool,
        QueryShotsTool,
    )
    from app.agents.tools.status_tools import CheckTaskStatusTool

    return {
        "get_chapter_script": GetChapterScriptTool(),
        "extract_assets": ExtractAssetsTool(),
        "query_assets": QueryAssetsTool(),
        "generate_image": GenerateImageTool(),
        "check_asset_status": CheckAssetStatusTool(),
        "extract_shots": ExtractShotsTool(),
        "bind_assets": BindAssetsTool(),
        "query_shots": QueryShotsTool(),
        "generate_frame": GenerateFrameTool(),
        "generate_video": GenerateVideoTool(),
        "check_task_status": CheckTaskStatusTool(),
    }


def _get_tools_for_agent(name: str) -> list[Tool]:
    """根据 agent 名称返回该 agent 可用的工具列表。"""
    registry = _build_tool_registry()
    tool_names = _AGENT_TOOL_NAMES.get(name, [])
    return [registry[n] for n in tool_names]


def create_agent_with_tools(name: str, llm: BaseChatModel) -> DirectorAgent | CharacterDesignerAgent | StoryboardAgent | ProductionAgent:
    """根据名称创建 specialist agent，自动装配该阶段所需的工具。

    Args:
        name: agent 名称，可选 director / character_designer / storyboard / production
        llm: 已绑定的 LLM 实例

    Returns:
        装配好工具的 specialist agent 实例
    """
    if name not in _AGENT_CLASSES:
        raise ValueError(f"Unknown agent name: {name}. Valid: {list(_AGENT_CLASSES)}")
    cls = _AGENT_CLASSES[name]
    tools = _get_tools_for_agent(name)
    return cls(llm, tools=tools)


__all__ = [
    "DirectorAgent",
    "CharacterDesignerAgent",
    "StoryboardAgent",
    "ProductionAgent",
    "create_agent_with_tools",
]
