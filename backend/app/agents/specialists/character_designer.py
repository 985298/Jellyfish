"""CharacterDesignerAgent: 角色/资产设计师，提取资产并生成图片。"""

from __future__ import annotations

from app.agents.core import SpecialistAgent

_CHARACTER_DESIGNER_SYSTEM_PROMPT = """你是 AI 短剧制作的角色/资产设计师。

你的职责是从剧本中提取资产（角色、场景、道具、服装），
并为每个资产生成图片。

使用 extract_assets 提取资产，使用 generate_image 生成图片，
使用 check_asset_status 检查生成状态，使用 query_assets 查询已有资产。

按以下顺序操作：
1. 获取剧本原文
2. 提取资产
3. 为每个资产生成图片
4. 检查所有图片生成状态
"""


class CharacterDesignerAgent(SpecialistAgent):
    """角色/资产设计师 Agent：提取资产 + 生成图片。"""

    agent_name: str = "character_designer"
    agent_description: str = "角色/资产设计师，提取资产并生成图片"

    @property
    def system_prompt(self) -> str:
        return _CHARACTER_DESIGNER_SYSTEM_PROMPT
