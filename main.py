import os

from dotenv import load_dotenv
import uvicorn


def main() -> None:
    load_dotenv()
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "boiltheplaylist.app:app",
        host="0.0.0.0",
        port=port,
        reload=True,
    )


if __name__ == "__main__":
    main()
