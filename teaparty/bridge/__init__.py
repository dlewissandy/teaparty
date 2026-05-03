"""Bridge server: exposes TeaParty state via REST endpoints and WebSocket.

Structure:
  server.py        — aiohttp app, route definitions, static file serving
  poller.py        — StateReader polling loop, state diffing, WebSocket event push
  message_relay.py — Per-session SqliteMessageBus polling, message event push
"""
