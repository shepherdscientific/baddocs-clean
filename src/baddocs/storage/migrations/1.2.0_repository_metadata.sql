-- Migration 1.2.0: Repository metadata

ALTER TABLE repositories ADD COLUMN owner VARCHAR(255);
ALTER TABLE repositories ADD COLUMN description TEXT;
ALTER TABLE repositories ADD COLUMN tags TEXT[];
