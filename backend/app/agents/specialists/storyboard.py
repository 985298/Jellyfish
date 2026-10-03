"""StoryboardAgent: 分镜师，提取分镜（分镜时已自带角色/场景引用）。"""

from __future__ import annotations

from app.agents.core import SpecialistAgent

_STORYBOARD_SYSTEM_PROMPT = """你是 AI 短剧制作的分镜师。

你的职责是将剧本分割为镜头。分镜输出已自带 character_names / scene_name 字段，
资产绑定在分镜阶段自动完成，不需要单独的绑定步骤。

使用 divide_shots 提取分镜，使用 query_shots 查询已有分镜。

按以下顺序操作：
1. 获取剧本原文
2. 提取分镜（分镜结果自带资产引用）
"""


class StoryboardAgent(SpecialistAgent):
    """分镜师 Agent：提取分镜（含资产引用）。"""

    agent_name: str = "storyboard"
    agent_description: str = "分镜师，提取分镜（分镜时自带资产引用）"

    @property
    def system_prompt(self) -> str:
        return _STORYBOARD_SYSTEM_PROMPT
