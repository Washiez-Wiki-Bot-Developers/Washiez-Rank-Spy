import logging

class ColorFormatter(logging.Formatter):
    def __init__(self, datefmt="%y-%m-%d %H:%M:%S"):
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
        self.TIME_COLOR = self.Fore.LIGHTBLACK_EX  # gray

        log_fmt = "%(asctime)s.%(msecs)03d %(levelname)-8s %(name)s: %(message)s"
        super().__init__(fmt=log_fmt, datefmt=datefmt)

    def format(self, record):
        # Colour the level name
        level_color = self.COLORS.get(record.levelno, "")
        levelname_colored = f"{level_color}{record.levelname}{self.Style.RESET_ALL}"
        original_levelname = record.levelname
        record.levelname = levelname_colored

        # Format the message
        formatted = super().format(record)

        # Restore levelname for other handlers
        record.levelname = original_levelname

        # Colour the entire timestamp (date + time + milliseconds)
        # The timestamp is always the first token before the first space
        first_space = formatted.find(" ")
        if first_space != -1:
            timestamp = formatted[:first_space]
            rest = formatted[first_space+1:]
            timestamp_colored = f"{self.TIME_COLOR}{timestamp}{self.Style.RESET_ALL}"
            formatted = f"{timestamp_colored} {rest}"

        return formatted

