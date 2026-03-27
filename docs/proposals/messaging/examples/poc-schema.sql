CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation TEXT NOT NULL,
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL NOT NULL
);
CREATE INDEX idx_messages_conv ON messages(conversation, timestamp);
