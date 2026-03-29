CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation TEXT NOT NULL,
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL NOT NULL,
    reply_to INTEGER REFERENCES messages(id),          -- links a reply to the message it answers
    ack_status TEXT NOT NULL DEFAULT 'na'
        CHECK(ack_status IN ('na', 'pending', 'acknowledged', 'cancelled'))
        -- 'na':           message does not request a reply (default for all messages)
        -- 'pending':      question posted, awaiting human response
        -- 'acknowledged': human reply received; ack_by records which reply message
        -- 'cancelled':    question withdrawn without resolution
);
CREATE INDEX idx_messages_conv ON messages(conversation, timestamp);
CREATE INDEX idx_messages_pending ON messages(conversation, ack_status)
    WHERE ack_status = 'pending';
