def main() -> int:
    try:
        import uvicorn
    except ImportError as error:
        raise SystemExit(f"uvicorn is required: {error}")
    uvicorn.run("jetson_app.api.app:create_app",factory=True,host="127.0.0.1",port=8081)
    return 0

if __name__ == "__main__": raise SystemExit(main())
