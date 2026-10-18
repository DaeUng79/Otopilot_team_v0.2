-- Existing original UI fields absent from the frozen shared project table.
-- Keep shared project columns stable; store evaluation scheduling as a local child.
CREATE TABLE IF NOT EXISTS project_evaluation_dates (
    project_id TEXT PRIMARY KEY NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    evaluation_date TEXT,
    updated_at TEXT NOT NULL,
    CHECK(evaluation_date IS NULL OR (length(evaluation_date)=10 AND evaluation_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'))
);
