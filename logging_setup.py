import logging
import sys, os, platform
from logging.handlers import RotatingFileHandler

try:
    from rich.logging import RichHandler

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    from logtail import LogtailHandler
    LOGTAIL_AVAILABLE = True
except Exception:
    LogtailHandler = None
    LOGTAIL_AVAILABLE = False
import dotenv
from coloured_log_handler import ColorFormatter
from discord_report_error_logs import DiscordErrorHandler

dotenv.load_dotenv()


class BasicFormatter(logging.Formatter):
    def __init__(self, datefmt="%y-%m-%d %H:%M:%S"):
        log_fmt = "%(asctime)s.%(msecs)03d %(levelname)-8s %(name)s: %(message)s"
        super().__init__(fmt=log_fmt, datefmt=datefmt)


from rich.logging import RichHandler
from rich.text import Text


class CustomRichHandler(RichHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Define your custom styles here
        self.level_styles = {
            logging.DEBUG: "cyan",
            logging.INFO: "green",
            logging.WARNING: "yellow",
            logging.ERROR: "red",
            logging.CRITICAL: "magenta bold",
        }

    def render_message(self, record, message: str) -> Text:
        # Let RichHandler build the base Text
        text = super().render_message(record, message)

        # Apply custom style to the level name
        level_style = self.level_styles.get(record.levelno)
        if level_style:
            # Replace the level name with styled version
            text.stylize(level_style, 0, len(record.levelname))

        return text


def setup_logging(
    name="bot", level=logging.INFO, bot=None, error_channel_id=None, rankspy_default_level=False
) -> logging.Logger:
    logging_setup_logger = logging.getLogger()
    try:
        if rankspy_default_level:
            if platform.system() == "Linux":
                print("Running on Linux")
                level = logging.INFO
            else:
                print(f"Not Linux (platform.system()={platform.system()})")
                level = logging.DEBUG

        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        handlers = []

        # Discord error handler
        if bot and error_channel_id:
            discord_error_handler = DiscordErrorHandler(bot, error_channel_id)
            discord_error_handler.setLevel(logging.ERROR)
            formatter = logging.Formatter(
                "%(asctime)s:%(levelname)s:%(name)s:%(filename)s:%(lineno)d: %(message)s"
            )
            discord_error_handler.setFormatter(formatter)
            handlers.append(discord_error_handler)
            root_logger.addHandler(discord_error_handler)

        # Console handler
        if RICH_AVAILABLE:
            level_styles = {
                "debug": "cyan",
                "info": "green",
                "warning": "yellow",
                "error": "red",
                "critical": "magenta bold",
            }
            console_handler = RichHandler(
                rich_tracebacks=True, show_time=True, show_level=True, show_path=True
            )
            console_handler.setFormatter(logging.Formatter("%(message)s"))
        else:
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setFormatter(ColorFormatter())
        handlers.append(console_handler)
        root_logger.addHandler(console_handler)

        # File handler (plain formatter, no ASCII)
        if platform.system() == "Linux" or platform.system() != "Windows":
            file_handler = RotatingFileHandler(
                "bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
        else:
            file_handler = logging.FileHandler("bot.log", encoding="utf-8")

        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        )
        handlers.append(file_handler)
        root_logger.addHandler(file_handler)

        # Error file handler (plain formatter, no ASCII)
        error_file_handler = logging.FileHandler("ERRORbot.log", encoding="utf-8")
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        )
        handlers.append(error_file_handler)
        root_logger.addHandler(error_file_handler)

        # Logtail handler
        logtail_source_token = os.getenv("logtail_source_token")
        logtail_host = os.getenv("logtail_host", "https://in.logtail.com")

        print("LOGTAIL host:", logtail_host)

        if LOGTAIL_AVAILABLE and logtail_source_token and logtail_host:
            try:
                logtail_handler = LogtailHandler(
                    source_token=logtail_source_token,
                    host=logtail_host,
                )
                logtail_handler.setFormatter(logging.Formatter("%(message)s"))
                logtail_handler.setLevel(level)
                handlers.append(logtail_handler)
                root_logger.addHandler(logtail_handler)
            except Exception as e:
                root_logger.error(f"Failed to initialize LogtailHandler: {e}")
        else:
            root_logger.warning("Logtail not available or environment not set. Skipping LogtailHandler.")

        # Silence noisy libraries
        connection_pool = logging.getLogger("urllib3.connectionpool")
        connection_pool.setLevel(logging.WARNING)

        logging.basicConfig(level=level, handlers=handlers, force=True)

        completed_logger = logging.getLogger(name)
        completed_logger.setLevel(level)
        completed_logger.propagate = True
        return completed_logger

    except Exception as e:
        logging_setup_logger.error(f"Error occurred: {e}")


if __name__ == "__main__":
    logger = setup_logging()
    logger.info("Logging is set up.")
