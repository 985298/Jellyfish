from __future__ import annotations

"""Studio 图片任务的数据层能力。"""

import base64
import mimetypes

from fastapi import HTTPException, status
from langchain_core.prompts import PromptTemplate as LcPromptTemplate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.contracts.provider import ProviderConfig
from app.models.llm import Model, ModelCategoryKey
from app.models.studio import AssetViewAngle, FileItem, PromptCategory, PromptTemplate, ShotFrameType
from app.services.llm import get_model_by_category
from app.services.llm.provider_config_resolver import resolve_provider_config


# ---------------------------------------------------------------------------
# 角色图片生成 - 优化后的 combined 提示词模板（character_image / actor_image 共用）
# ---------------------------------------------------------------------------
# 设计目标：让角色图更稳定、更一致、更专业。
# 结构分 5 段：①角色锚定 ②角色描述 ③视角 ④身份一致性约束 ⑤画面风格锚定 ⑥负面提示。
# 兼容两条渲染路径：
#   - 路由创建任务路径 `_apply_prompt_template`：仅传入 description（用户 prompt 文本），
#     其余变量为空 → 经 Jinja2 条件分支自动跳过可选段，落到正面视角默认分支。
#   - 服务渲染路径 `build_character_image_base_draft`：传入 name/description/visual_style/
#     style/view_angle/quality_level/format 等结构化字段 → 完整渲染各段。
# 变量列表须与 sql/009-upgrade-combined-character-template.sql 保持一致。
CHARACTER_COMBINED_TEMPLATE_VARIABLES: list[str] = [
    "name",
    "description",
    "visual_style",
    "style",
    "view_angle",
    "extra_details",
    "quality_level",
    "format",
]

CHARACTER_COMBINED_TEMPLATE_CONTENT: str = (
    "【角色锚定 / Character Anchor】\n"
    "{%- if visual_style %}\n视觉风格：{{ visual_style }}\n{%- endif %}\n"
    "{%- if style %}\n画面风格：{{ style }}\n{%- endif %}\n"
    "{%- if name %}\n角色名：{{ name }}\n{%- endif %}\n"
    "\n"
    "【角色描述 / Character Description】\n"
    "{{ description }}\n"
    "{%- if extra_details %}\n{{ extra_details }}\n{%- endif %}\n"
    "\n"
    "【视角 / View Angle】\n"
    "{%- if view_angle %}\n"
    "{{ view_angle }}，正确的透视与轮廓，头部朝向自然符合该视角\n"
    "{%- else %}\n"
    "正面视角，角色直视镜头，居中构图，头部朝向自然\n"
    "{%- endif %}\n"
    "\n"
    "【身份一致性约束 / Identity Consistency】\n"
    "高度一致的人物，身份保留：与参考图像中完全相同的同一个人的肖像，"
    "100% 身份一致性——相同的面部结构、相同的发型、相同的服装、相同的妆容与配饰、"
    "相同的年龄段与体型。若存在参考图 1（演员正面图），以该面部为身份基准；"
    "若存在参考图 2（服装图），使用其服装。无任何身份漂移、无变脸、无换人。\n"
    "演员姿态：站立挺直，中立姿势，双手自然下垂\n"
    "\n"
    "【画面风格锚定 / Style Anchor】\n"
    "高质量电影级{% if visual_style %}{{ visual_style }}{% else %}写实{% endif %}"
    "人像摄影，8k 分辨率，极致锐度与纹理\n"
    "电影感浅景深，f/1.4 大光圈，背景虚化自然明显\n"
    "专业商业人像摄影 + 当代电影剧照质感\n"
    "经典三分法或黄金分割构图，角色为画面主体，完整从头到脚无裁切\n"
    "{%- if visual_style and style %}\n"
    "完美贴合 {{ visual_style }} 视觉语言与 {{ style }} 整体氛围，风格高度一致\n"
    "{%- endif %}\n"
    "\n"
    "【负面提示 / Negative Prompt】\n"
    "low quality, worst quality, blurry, deformed, bad anatomy, bad hands, "
    "missing fingers, extra limbs, poorly drawn face, bad proportions, "
    "inconsistent face, face swap, different person, identity drift, "
    "clothing mismatch, hairstyle change, age drift, "
    "watermark, text, logo, signature, overexposed, underexposed, "
    "plastic skin, doll, lowres, jpeg artifacts, grainy"
    "{%- if visual_style and (\"动漫\" in visual_style or \"anime\" in visual_style.lower()) %}"
    ", bad anime, deformed anime, low quality anime, flat color, flat shading, 3d render, cgi"
    "{%- else %}"
    ", cartoon, 3d render, cgi, illustration, painting, sketch, anime"
    "{%- endif %}"
    "{%- if style and (\"古装\" in style or \"古代\" in style) %}"
    ", modern clothing, modern background, contemporary elements"
    "{%- endif %}"
)


def render_character_combined_prompt(description: str, **extra_variables: object) -> str:
    """渲染角色 combined 模板（最小侵入入口）。

    主要供 `_apply_prompt_template` 在创建任务路径上调用：当 DB 未配置 combined 模板时，
    直接用内置常量渲染，保证角色图提示词质量不依赖 DB 种子数据。
    """
    variables: dict[str, object] = {"description": description or ""}
    variables.update(extra_variables)
    return render_prompt_template_content(
        CHARACTER_COMBINED_TEMPLATE_CONTENT,
        variables=variables,
    )


async def resolve_image_model(db: AsyncSession, model_id: str | None, project_id: str | None = None) -> Model:
    """根据显式 model_id 或项目绑定或默认图片模型解析 Model。"""
    try:
        return await get_model_by_category(
            db,
            ModelCategoryKey.image,
            model_or_id=model_id,
            project_id=project_id,
        )
    except HTTPException as e:
        if e.status_code == status.HTTP_404_NOT_FOUND and model_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Configured model_id not found in DB: {model_id}",
            ) from e
        if e.status_code == status.HTTP_503_SERVICE_UNAVAILABLE and not model_id:
            # 保持既有行为：未传 model_id 时，仅允许读取 ModelSettings.default_image_model_id。
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No image model configured in DB (missing explicit model_id and ModelSettings.default_image_model_id)",
            ) from e
        if e.status_code == status.HTTP_503_SERVICE_UNAVAILABLE and model_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Configured model is not an image model: {model_id}",
            ) from e
        raise


async def load_provider_config(db: AsyncSession, provider_id: str) -> ProviderConfig:
    """根据 provider_id 从 DB 解析 ProviderConfig。"""
    resolved = await resolve_provider_config(
        db,
        provider_id=provider_id,
        category=ModelCategoryKey.image,
    )
    return ProviderConfig(
        provider=resolved.provider_key,  # type: ignore[arg-type]
        api_key=resolved.api_key,
        base_url=resolved.base_url,
    )


def prompt_from_description(description: str, *, not_found_msg: str) -> str:
    prompt = (description or "").strip()
    if not prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=not_found_msg)
    return prompt


def is_front_view(view_angle: AssetViewAngle | str | None) -> bool:
    if view_angle is None:
        return False
    value = view_angle.value if isinstance(view_angle, AssetViewAngle) else str(view_angle)
    return value == AssetViewAngle.front.value


def map_view_angle_for_prompt(view_angle: AssetViewAngle | str | None) -> str:
    if view_angle is None:
        return ""
    raw = view_angle.value if isinstance(view_angle, AssetViewAngle) else str(view_angle)
    view_angle_map = {
        "RIGH": "纯右側面,严格右侧面，90度纯侧面轮廓，耳朵清晰可见",
        "RIGHT": "纯右側面,严格右侧面，90度纯侧面轮廓，耳朵清晰可见",
        "LEFT": "纯左侧面,严格左侧面，90度纯侧面轮廓，耳朵清晰可见",
        "BACK": "正后方,正后方视角，完全背对镜头，只能看到后脑勺和后背",
    }
    return view_angle_map.get(raw, raw)


async def resolve_prompt_template(
    db: AsyncSession,
    *,
    category: PromptCategory,
) -> PromptTemplate | None:
    stmt = (
        select(PromptTemplate)
        .where(PromptTemplate.category == category)
        .order_by(PromptTemplate.is_default.desc(), PromptTemplate.updated_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


def render_prompt_template_content(
    content: str,
    *,
    variables: dict[str, object],
) -> str:
    tmpl = LcPromptTemplate.from_template(template=content,template_format="jinja2")
    render_vars = {k: str(variables.get(k, "")) for k in tmpl.input_variables}
    return tmpl.format(**render_vars).strip()


async def build_prompt_with_template(
    db: AsyncSession,
    *,
    category: PromptCategory,
    variables: dict[str, object],
    fallback_prompt: str,
    not_found_msg: str,
) -> str:
    template = await resolve_prompt_template(db, category=category)
    if template is not None and template.content:
        rendered = render_prompt_template_content(template.content, variables=variables)
        if rendered:
            return rendered
    return prompt_from_description(fallback_prompt, not_found_msg=not_found_msg)


async def resolve_front_image_ref(
    db: AsyncSession,
    *,
    image_model: type,
    parent_field_name: str,
    parent_id: str,
    preferred_quality_level: object | None,
) -> dict[str, str] | None:
    parent_field = getattr(image_model, parent_field_name)
    stmt = (
        select(image_model)
        .where(
            parent_field == parent_id,
            image_model.view_angle == AssetViewAngle.front,
            image_model.file_id.is_not(None),
        )
        .order_by(image_model.created_at.desc(), image_model.id.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    if not rows:
        return None

    target = rows[0]
    if preferred_quality_level is not None:
        for row in rows:
            if row.quality_level == preferred_quality_level:
                target = row
                break

    if not target.file_id:
        return None

    file_obj = await db.get(FileItem, target.file_id)
    if file_obj is None or not file_obj.storage_key:
        return None

    try:
        content = await storage.download_file(key=file_obj.storage_key)
    except Exception:  # noqa: BLE001
        return None
    if not content:
        return None

    content_type: str | None = None
    try:
        info = await storage.get_file_info(key=file_obj.storage_key)
        content_type = (info.content_type or "").strip().lower() or None
    except Exception:  # noqa: BLE001
        content_type = None

    if not content_type:
        guessed_type, _ = mimetypes.guess_type(file_obj.storage_key)
        content_type = (guessed_type or "").strip().lower() or None

    if not content_type or not content_type.startswith("image/"):
        content_type = "image/png"

    image_format = content_type.split("/", 1)[1].split(";", 1)[0].strip().lower() or "png"
    encoded = base64.b64encode(content).decode("ascii")
    data_url = f"data:image/{image_format};base64,{encoded}"
    return {"image_url": data_url}


async def resolve_ordered_image_refs(
    db: AsyncSession,
    *,
    image_model: type,
    parent_field_name: str,
    parent_id: str,
    view_angles: tuple[AssetViewAngle, ...],
) -> list[dict[str, str]]:
    """按指定 view_angles 顺序，解析参考图（data url）。"""
    parent_field = getattr(image_model, parent_field_name)
    stmt = (
        select(image_model)
        .where(
            parent_field == parent_id,
            image_model.file_id.is_not(None),
        )
        .order_by(image_model.created_at.desc(), image_model.id.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    if not rows:
        return []

    best_by_angle: dict[str, object] = {}
    for row in rows:
        angle = getattr(row, "view_angle", None)
        key = angle.value if isinstance(angle, AssetViewAngle) else str(angle)
        if key and key not in best_by_angle:
            best_by_angle[key] = row

    out: list[dict[str, str]] = []
    for angle in view_angles:
        row = best_by_angle.get(angle.value)
        if row is None:
            continue
        file_id = getattr(row, "file_id", None)
        if not file_id:
            continue
        file_obj = await db.get(FileItem, str(file_id))
        if file_obj is None or not file_obj.storage_key:
            continue
        try:
            content = await storage.download_file(key=file_obj.storage_key)
        except Exception:  # noqa: BLE001
            continue
        if not content:
            continue

        content_type: str | None = None
        try:
            info = await storage.get_file_info(key=file_obj.storage_key)
            content_type = (info.content_type or "").strip().lower() or None
        except Exception:  # noqa: BLE001
            content_type = None
        if not content_type:
            guessed_type, _ = mimetypes.guess_type(file_obj.storage_key)
            content_type = (guessed_type or "").strip().lower() or None
        if not content_type or not content_type.startswith("image/"):
            content_type = "image/png"

        image_format = content_type.split("/", 1)[1].split(";", 1)[0].strip().lower() or "png"
        encoded = base64.b64encode(content).decode("ascii")
        data_url = f"data:image/{image_format};base64,{encoded}"
        out.append({"image_url": data_url})
    return out


def asset_prompt_category(
    *,
    relation_type: str,
    is_front_view: bool,
) -> PromptCategory:
    mapping = {
        "actor_image": (PromptCategory.actor_image_front, PromptCategory.actor_image_other),
        "prop_image": (PromptCategory.prop_image_front, PromptCategory.prop_image_other),
        "scene_image": (PromptCategory.scene_image_front, PromptCategory.scene_image_other),
        "costume_image": (PromptCategory.costume_image_front, PromptCategory.costume_image_other),
    }
    front_category, other_category = mapping[relation_type]
    return front_category if is_front_view else other_category


def shot_frame_prompt_category(frame_type: ShotFrameType | str) -> PromptCategory:
    value = frame_type.value if isinstance(frame_type, ShotFrameType) else str(frame_type)
    if value == ShotFrameType.first.value:
        return PromptCategory.frame_head_image
    if value == ShotFrameType.last.value:
        return PromptCategory.frame_tail_image
    return PromptCategory.frame_key_image
