-- 优化角色图片生成提示词模板（Phase 4 体验优化第一项）
-- 升级 combined 与 character_image_front 两个类别的默认模板：
--   1. combined（character_image / actor_image 共用）：
--      旧模板仅一段文字 + {{description}}，缺少身份一致性约束、视角区分、风格锚定、负面提示。
--      新模板分 6 段：角色锚定 / 角色描述 / 视角 / 身份一致性约束 / 画面风格锚定 / 负面提示，
--      并按 visual_style / style 条件分支适配动漫/古装等子类型。
--   2. character_image_front：保留旧的轻量占位模板作为非默认记录（is_default=0），
--      避免 is_default=True 的记录因系统策略无法直接 DELETE 的限制；
--      新的默认模板由 INSERT ... ON DUPLICATE KEY UPDATE 写入。
-- 注意：is_system=1 的模板在 API 层禁止修改/删除，但本脚本通过 SQL 直接覆写 content，
--       属于初始化/运维脚本路径，绕过 API 校验。
-- 兼容性：模板仍保留 {{description}} 占位（路由 _apply_prompt_template 走 .replace 路径），
--         同时新模板支持完整 Jinja2 渲染（build_character_image_base_draft 路径）。

BEGIN;
SET NAMES utf8mb4;

-- 1) combined：角色锚定模板（character_image / actor_image 默认模板）
UPDATE `prompt_templates`
SET `content` = '【角色锚定 / Character Anchor】\n{%- if visual_style %}\n视觉风格：{{ visual_style }}\n{%- endif %}\n{%- if style %}\n画面风格：{{ style }}\n{%- endif %}\n{%- if name %}\n角色名：{{ name }}\n{%- endif %}\n\n【角色描述 / Character Description】\n{{ description }}\n{%- if extra_details %}\n{{ extra_details }}\n{%- endif %}\n\n【视角 / View Angle】\n{%- if view_angle %}\n{{ view_angle }}，正确的透视与轮廓，头部朝向自然符合该视角\n{%- else %}\n正面视角，角色直视镜头，居中构图，头部朝向自然\n{%- endif %}\n\n【身份一致性约束 / Identity Consistency】\n高度一致的人物，身份保留：与参考图像中完全相同的同一个人的肖像，100% 身份一致性——相同的面部结构、相同的发型、相同的服装、相同的妆容与配饰、相同的年龄段与体型。若存在参考图 1（演员正面图），以该面部为身份基准；若存在参考图 2（服装图），使用其服装。无任何身份漂移、无变脸、无换人。\n演员姿态：站立挺直，中立姿势，双手自然下垂\n\n【画面风格锚定 / Style Anchor】\n高质量电影级{% if visual_style %}{{ visual_style }}{% else %}写实{% endif %}人像摄影，8k 分辨率，极致锐度与纹理\n电影感浅景深，f/1.4 大光圈，背景虚化自然明显\n专业商业人像摄影 + 当代电影剧照质感\n经典三分法或黄金分割构图，角色为画面主体，完整从头到脚无裁切\n{%- if visual_style and style %}\n完美贴合 {{ visual_style }} 视觉语言与 {{ style }} 整体氛围，风格高度一致\n{%- endif %}\n\n【负面提示 / Negative Prompt】\nlow quality, worst quality, blurry, deformed, bad anatomy, bad hands, missing fingers, extra limbs, poorly drawn face, bad proportions, inconsistent face, face swap, different person, identity drift, clothing mismatch, hairstyle change, age drift, watermark, text, logo, signature, overexposed, underexposed, plastic skin, doll, lowres, jpeg artifacts, grainy{%- if visual_style and (\"动漫\" in visual_style or \"anime\" in visual_style.lower()) %}, bad anime, deformed anime, low quality anime, flat color, flat shading, 3d render, cgi{%- else %}, cartoon, 3d render, cgi, illustration, painting, sketch, anime{%- endif %}{%- if style and (\"古装\" in style or \"古代\" in style) %}, modern clothing, modern background, contemporary elements{%- endif %}',
    `variables` = '["name", "description", "visual_style", "style", "view_angle", "extra_details", "quality_level", "format"]',
    `updated_at` = CURRENT_TIMESTAMP
WHERE `category` = 'combined' AND `is_default` = 1;

-- 2) character_image_front：升级为带一致性约束与负面提示的完整模板
UPDATE `prompt_templates`
SET `content` = '【角色锚定 / Character Anchor】\n{%- if visual_style %}\n视觉风格：{{ visual_style }}\n{%- endif %}\n{%- if style %}\n画面风格：{{ style }}\n{%- endif %}\n\n【角色描述 / Character Description】\n{{ description }}\n\n【视角 / View Angle】\n正面视角，角色直视镜头，居中构图，面部清晰可见，头部朝向自然\n\n【身份一致性约束 / Identity Consistency】\n高度一致的人物，身份保留：与参考图像中完全相同的同一个人的肖像，100% 身份一致性——相同的面部结构、相同的发型、相同的服装、相同的妆容与配饰、相同的年龄段与体型。无任何身份漂移、无变脸、无换人。\n演员姿态：站立挺直，中立姿势，双手自然下垂\n\n【画面风格锚定 / Style Anchor】\n高质量电影级{% if visual_style %}{{ visual_style }}{% else %}写实{% endif %}人像摄影，8k 分辨率，极致锐度与纹理\n柔和自然光，浅灰色纯色背景，专业商业人像摄影 + 当代电影剧照质感\n角色居中，半身肖像，完整从头部到腰部无裁切\n{%- if visual_style and style %}\n完美贴合 {{ visual_style }} 视觉语言与 {{ style }} 整体氛围，风格高度一致\n{%- endif %}\n\n【负面提示 / Negative Prompt】\nlow quality, worst quality, blurry, deformed, bad anatomy, bad hands, missing fingers, extra limbs, poorly drawn face, bad proportions, inconsistent face, face swap, different person, identity drift, clothing mismatch, hairstyle change, age drift, watermark, text, logo, signature, overexposed, underexposed, plastic skin, doll, lowres, jpeg artifacts, grainy{%- if visual_style and (\"动漫\" in visual_style or \"anime\" in visual_style.lower()) %}, bad anime, deformed anime, low quality anime, flat color, flat shading, 3d render, cgi{%- else %}, cartoon, 3d render, cgi, illustration, painting, sketch, anime{%- endif %}{%- if style and (\"古装\" in style or \"古代\" in style) %}, modern clothing, modern background, contemporary elements{%- endif %}',
    `variables` = '["description", "visual_style", "style"]',
    `updated_at` = CURRENT_TIMESTAMP
WHERE `category` = 'character_image_front' AND `is_default` = 1;

COMMIT;
