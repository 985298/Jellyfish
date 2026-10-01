"""ProductionAgent: 后期制作师，生成帧图和视频。"""

from __future__ import annotations

from app.agents.core import SpecialistAgent

_PRODUCTION_SYSTEM_PROMPT = """你是 AI 短剧制作的后期制作师。

你的职责是为每个镜头生成帧图和视频。

使用 query_shots 查询镜头，使用 generate_frame 生成帧图，
使用 generate_video 生成视频，使用 check_task_status 检查任务状态。

按以下顺序操作：
1. 查询所有镜头
2. 为每个镜头生成帧图
3. 检查帧图生成状态
4. 为每个镜头生成视频
5. 检查视频生成状态
"""


class ProductionAgent(SpecialistAgent):
    """后期制作师 Agent：生成帧图 + 生成视频。"""

    agent_name: str = "production"
    agent_description: str = "后期制作师，生成帧图和视频"

    @property
    def system_prompt(self) -> str:
        return _PRODUCTION_SYSTEM_PROMPT
