CREATE TABLE IF NOT EXISTS data_generation_state (
    namespace TEXT PRIMARY KEY CHECK(length(trim(namespace)) > 0),
    generation INTEGER NOT NULL CHECK(generation >= 0)
);

INSERT INTO data_generation_state(namespace, generation)
VALUES
    ('report_structure', 0),
    ('classification_catalog', 0),
    ('settings', 0),
    ('privacy_catalog', 0),
    ('database_replacement', 0)
ON CONFLICT(namespace) DO NOTHING;
