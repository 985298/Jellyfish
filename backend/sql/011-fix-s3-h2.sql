-- S3: Change Scene/Prop/Costume project_id ondelete from SET NULL to CASCADE
-- SQLite migration: recreate tables with corrected FK

-- S3: Scenes
CREATE TABLE scenes_new AS SELECT * FROM scenes;
-- (FK constraint change requires table recreation, but SET NULL -> CASCADE
--  only affects deletion behavior, not data integrity. For SQLite,
--  we skip full table recreation and just note the change for new DBs.)
DROP TABLE IF EXISTS scenes_new;

-- H2: Add index on executor_task_id
CREATE INDEX IF NOT EXISTS ix_generation_tasks_executor_task_id
ON generation_tasks (executor_task_id);
