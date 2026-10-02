-- H1: Add is_primary column to SceneImage/PropImage/CostumeImage/ActorImage tables
-- CharacterImage already has this column
ALTER TABLE scene_images ADD COLUMN is_primary BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE prop_images ADD COLUMN is_primary BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE costume_images ADD COLUMN is_primary BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE actor_images ADD COLUMN is_primary BOOLEAN NOT NULL DEFAULT 0;
