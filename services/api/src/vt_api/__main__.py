"""Entry point (`vt-api` or `python -m vt_api`): uvicorn configured from `Settings`."""

import uvicorn

from vt_api.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "vt_api.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        server_header=False,
    )


if __name__ == "__main__":
    main()
