"""Entry point (`vt-pron` or `python -m vt_pron`): uvicorn configured from `Settings`."""

import uvicorn

from vt_pron.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "vt_pron.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        server_header=False,
    )


if __name__ == "__main__":
    main()
