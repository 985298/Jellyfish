-- 011: Add asset_stage column to chapters table
-- Tracks the asset extraction stage status (not_started/running/done/failed/blocked/partial)
-- inferred from pipeline-status, surfaced to ChapterRead so chapterPreparation can branch on it.

PRAGMA foreign_keys=OFF;

ALTER TABLE chapters ADD COLUMN asset_stage VARCHAR(32);

PRAGMA foreign_keys=ON;
