-- S1: Fix global unique name → project-scoped unique (project_id, name) for Scene/Prop/Costume
-- S2: Fix ProjectActorLink constraint (remove nullable chapter_id/shot_id)
-- SQLite migration: recreate tables with corrected constraints

-- S1: Scenes
CREATE TABLE scenes_new (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    style VARCHAR(64),
    view_count INTEGER,
    tags JSON,
    project_id VARCHAR(64),
    prompt_template_id VARCHAR(64),
    visual_style VARCHAR(64),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (project_id, name)
);
INSERT INTO scenes_new SELECT * FROM scenes;
DROP TABLE scenes;
ALTER TABLE scenes_new RENAME TO scenes;
CREATE INDEX ix_scenes_project_id ON scenes (project_id);
CREATE INDEX ix_scenes_name ON scenes (name);
CREATE INDEX ix_scenes_prompt_template_id ON scenes (prompt_template_id);

-- S1: Props
CREATE TABLE props_new (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    style VARCHAR(64),
    view_count INTEGER,
    tags JSON,
    project_id VARCHAR(64),
    prompt_template_id VARCHAR(64),
    visual_style VARCHAR(64),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (project_id, name)
);
INSERT INTO props_new SELECT * FROM props;
DROP TABLE props;
ALTER TABLE props_new RENAME TO props;
CREATE INDEX ix_props_project_id ON props (project_id);
CREATE INDEX ix_props_name ON props (name);
CREATE INDEX ix_props_prompt_template_id ON props (prompt_template_id);

-- S1: Costumes
CREATE TABLE costumes_new (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    style VARCHAR(64),
    view_count INTEGER,
    tags JSON,
    project_id VARCHAR(64),
    prompt_template_id VARCHAR(64),
    visual_style VARCHAR(64),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (project_id, name)
);
INSERT INTO costumes_new SELECT * FROM costumes;
DROP TABLE costumes;
ALTER TABLE costumes_new RENAME TO costumes;
CREATE INDEX ix_costumes_project_id ON costumes (project_id);
CREATE INDEX ix_costumes_name ON costumes (name);
CREATE INDEX ix_costumes_prompt_template_id ON costumes (prompt_template_id);

-- S2: ProjectActorLinks (remove nullable chapter_id/shot_id from unique)
CREATE TABLE project_actor_links_new (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    actor_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    chapter_id VARCHAR(64),
    shot_id VARCHAR(64),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (actor_id, project_id)
);
INSERT INTO project_actor_links_new SELECT id, actor_id, project_id, chapter_id, shot_id, created_at, updated_at FROM project_actor_links;
DROP TABLE project_actor_links;
ALTER TABLE project_actor_links_new RENAME TO project_actor_links;
CREATE INDEX ix_project_actor_links_actor_id ON project_actor_links (actor_id);
CREATE INDEX ix_project_actor_links_project_id ON project_actor_links (project_id);
CREATE INDEX ix_project_actor_links_chapter_id ON project_actor_links (chapter_id);
CREATE INDEX ix_project_actor_links_shot_id ON project_actor_links (shot_id);
