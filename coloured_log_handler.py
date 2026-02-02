import logging

class ColorFormatter(logging.Formatter):
    def __init__(self, datefmt="%y-%m-%d %H:%M:%S"):
        from colorama import Fore, Style, init
        init(autoreset=True)

        self.Fore = Fore
        self.Style = Style
        self.COLORS = {
            logging.DEBUG: Fore.CYAN,
            logging.INFO: Fore.GREEN,
            logging.WARNING: Fore.YELLOW,
            logging.ERROR: Fore.RED,
            logging.CRITICAL: Fore.MAGENTA + Style.BRIGHT,
        }
        self.TIME_COLOR = Fore.LIGHTBLACK_EX

        log_fmt = "%(asctime)s.%(msecs)03d %(levelname)-8s %(name)s: %(message)s"
        super().__init__(fmt=log_fmt, datefmt=datefmt)

    def format(self, record):
        level_color = self.COLORS.get(record.levelno, "")
        levelname_colored = f"{level_color}{record.levelname}{self.Style.RESET_ALL}"
        original_levelname = record.levelname
        record.levelname = levelname_colored

        formatted = super().format(record)
        record.levelname = original_levelname

        first_space = formatted.find(" ")
        if first_space != -1:
            timestamp = formatted[:first_space]
            rest = formatted[first_space+1:]
            timestamp_colored = f"{self.TIME_COLOR}{timestamp}{self.Style.RESET_ALL}"
            formatted = f"{timestamp_colored} {rest}"

        return formatted
