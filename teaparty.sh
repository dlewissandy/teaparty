pkill -9 uvicorn
pkill -9 python
uv run uvicorn teaparty_app.main:app --reload