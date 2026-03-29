CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation TEXT NOT NULL,
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL NOT NULL
);
CREATE INDEX idx_messages_conv ON messages(conversation, timestamp);

CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'active',
    created_at REAL NOT NULL,
    awaiting_input INTEGER NOT NULL DEFAULT 0
        -- 0: no pending human input; 1: MessageBusInputProvider is waiting for a reply
);
