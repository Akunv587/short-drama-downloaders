-- zaizaicat database schema
CREATE TABLE IF NOT EXISTS download_tasks (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    platform TEXT NOT NULL,
    drama_name TEXT,
    episode_number INTEGER,
    episode_range TEXT,
    status TEXT DEFAULT 'queued',
    progress REAL DEFAULT 0,
    output_path TEXT,
    error_message TEXT,
    total_episodes INTEGER DEFAULT 1,
    completed_episodes INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS download_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drama_name TEXT NOT NULL,
    platform TEXT NOT NULL,
    episode_count INTEGER DEFAULT 1,
    total_size_bytes INTEGER,
    download_path TEXT,
    completed_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dramas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    play_count INTEGER,
    episode_count INTEGER,
    first_episode_url TEXT,
    tags TEXT,
    publish_date TEXT,
    source_platform TEXT,
    status TEXT DEFAULT 'unwatched',
    notes TEXT,
    data_source TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Default settings
INSERT OR IGNORE INTO settings (key, value) VALUES ('theme', 'light');
INSERT OR IGNORE INTO settings (key, value) VALUES ('download_dir', '');
INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_normalize', 'false');
INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_add_drama', 'true');
INSERT OR IGNORE INTO settings (key, value) VALUES ('target_lufs', '-14.0');
INSERT OR IGNORE INTO settings (key, value) VALUES ('max_true_peak', '-1.0');
