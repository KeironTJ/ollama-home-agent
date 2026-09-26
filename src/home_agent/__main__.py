import uvicorn

from .app import create_app
from .core.config import Settings


def main() -> None:
    while True:
        settings = Settings.load()
        application = create_app(settings)
        config = uvicorn.Config(application, host=settings.host, port=settings.port, reload=False)
        server = uvicorn.Server(config)

        def request_shutdown() -> None:
            server.should_exit = True

        application.state.shutdown_callback = request_shutdown
        server.run()
        if not application.state.restart_requested:
            break


if __name__ == "__main__":
    main()
