-- Migration 1.1.0: Cross-codebase database support

ALTER TABLE repositories ADD COLUMN external_id VARCHAR(255);
ALTER TABLE repositories ADD COLUMN metadata JSONB DEFAULT '{}';

CREATE TABLE IF NOT EXISTS repository_links (
    id SERIAL PRIMARY KEY,
    source_repo_id INTEGER REFERENCES repositories(id),
    target_repo_id INTEGER REFERENCES repositories(id),
    link_type VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
