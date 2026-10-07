"""ProductionAgent: 后期制作师，生成帧图和视频。"""

from __future__ import annotations

from app.agents.core import SpecialistAgent

_PRODUCTION_SYSTEM_PROMPT = """你是 AI 短剧制作的后期制作师。

你的职责是为镜头生成关键帧图和视频，保证角色一致性。

操作流程：
1. 使用 query_shots 查询所有镜头
2. 对每个镜头调 generate_frame 生成关键帧（工具自动查角色参考图走 img2img；无角色镜头自动走纯文生图）
3. 所有关键帧生成后，调 generate_videos_batch 一次性提交所有视频任务（视频从关键帧 first_frame 起播）
4. 提交后立即返回结果，不要等待视频生成完成

使用 generate_frame 生成帧图，使用 generate_videos_batch 生成视频。
"""


class ProductionAgent(SpecialistAgent):
    """后期制作师 Agent：生成帧图 + 生成视频。"""

    agent_name: str = "production"
    agent_description: str = "后期制作师，生成帧图和视频"

    @property
    def system_prompt(self) -> str:
        return _PRODUCTION_SYSTEM_PROMPT
