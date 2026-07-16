CREATE TABLE IF NOT EXISTS report_structure_revision_state (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    generation INTEGER NOT NULL CHECK(generation >= 0)
);

INSERT INTO report_structure_revision_state(singleton_id, generation)
VALUES (1, 0)
ON CONFLICT(singleton_id) DO NOTHING;
