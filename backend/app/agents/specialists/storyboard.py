"""StoryboardAgent: 分镜师，提取分镜并绑定资产。"""

from __future__ import annotations

from app.agents.core import SpecialistAgent

_STORYBOARD_SYSTEM_PROMPT = """你是 AI 短剧制作的分镜师。

你的职责是将剧本分割为镜头，并将资产绑定到对应镜头。

使用 extract_shots 提取分镜，使用 bind_assets 绑定资产到分镜，
使用 query_shots 查询已有分镜。

按以下顺序操作：
1. 获取剧本原文
2. 提取分镜
3. 绑定资产到分镜
"""


class StoryboardAgent(SpecialistAgent):
    """分镜师 Agent：提取分镜 + 绑定资产。"""

    agent_name: str = "storyboard"
    agent_description: str = "分镜师，提取分镜并绑定资产"

    @property
    def system_prompt(self) -> str:
        return _STORYBOARD_SYSTEM_PROMPT
