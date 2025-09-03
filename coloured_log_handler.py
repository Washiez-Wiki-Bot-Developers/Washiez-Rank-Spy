import logging

# --- Custom formatter with internal colorama handling ---
class ColorFormatter(logging.Formatter):
    def __init__(self, datefmt="%y-%m-%d %H:%M:%S"):
        # Import and init colorama here so it's self-contained
        from colorama import Fore, Style, init
        init(autoreset=True)

        self.Fore = Fore
        self.Style = Style
        self.COLORS = {
            logging.DEBUG: self.Fore.CYAN,
            logging.INFO: self.Fore.GREEN,
            logging.WARNING: self.Fore.YELLOW,
            logging.ERROR: self.Fore.RED,
            logging.CRITICAL: self.Fore.MAGENTA + self.Style.BRIGHT
        }

        # Include milliseconds in the format string
        log_fmt = "%(asctime)s.%(msecs)03d %(levelname)-8s %(name)s: %(message)s"
        super().__init__(fmt=log_fmt, datefmt=datefmt)

    def format(self, record):
        # Colour only the level name
        level_color = self.COLORS.get(record.levelno, "")
        record.levelname = f"{level_color}{record.levelname}{self.Style.RESET_ALL}"
        return super().format(record)