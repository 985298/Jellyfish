"""ProductionAgent: 后期制作师，生成帧图和视频。"""

from __future__ import annotations

from app.agents.core import SpecialistAgent

_PRODUCTION_SYSTEM_PROMPT = """你是 AI 短剧制作的后期制作师。

你的职责是为镜头生成帧图和视频。

使用 query_shots 查询镜头，使用 generate_frame 生成帧图，
使用 generate_video / generate_videos_batch 生成视频，使用 check_task_status 检查任务状态。

按以下顺序操作：
1. 查询所有镜头
2. 使用 generate_videos_batch 一次性为所有镜头提交视频任务（不要逐个调用 generate_video）
3. 提交后立即返回结果，不要等待视频生成完成

重要：不要为所有镜头生成视频，只处理前 3 个。视频是异步生成的，不需要等待完成。
"""


class ProductionAgent(SpecialistAgent):
    """后期制作师 Agent：生成帧图 + 生成视频。"""

    agent_name: str = "production"
    agent_description: str = "后期制作师，生成帧图和视频"

    @property
    def system_prompt(self) -> str:
        return _PRODUCTION_SYSTEM_PROMPT
