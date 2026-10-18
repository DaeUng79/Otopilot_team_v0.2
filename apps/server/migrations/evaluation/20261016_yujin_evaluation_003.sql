CREATE TABLE IF NOT EXISTS score_sheet_opinions (
    sheet_id TEXT PRIMARY KEY REFERENCES score_sheets(id) ON DELETE RESTRICT,
    opinion TEXT NOT NULL DEFAULT '' CHECK(length(opinion)<=4000)
);
CREATE TRIGGER score_opinion_insert_guard BEFORE INSERT ON score_sheet_opinions
WHEN (SELECT status FROM score_sheets WHERE id=NEW.sheet_id)<>'DRAFT'
BEGIN SELECT RAISE(ABORT,'submitted opinion is immutable'); END;
CREATE TRIGGER score_opinion_update_guard BEFORE UPDATE ON score_sheet_opinions
WHEN NEW.sheet_id<>OLD.sheet_id OR (SELECT status FROM score_sheets WHERE id=OLD.sheet_id)<>'DRAFT'
BEGIN SELECT RAISE(ABORT,'submitted opinion is immutable'); END;
CREATE TRIGGER score_opinion_delete_guard BEFORE DELETE ON score_sheet_opinions
WHEN (SELECT status FROM score_sheets WHERE id=OLD.sheet_id)<>'DRAFT'
BEGIN SELECT RAISE(ABORT,'submitted opinion is immutable'); END;
