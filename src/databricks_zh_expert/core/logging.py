import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"不支持的日志级别：{level}")

    logging.basicConfig(
        level=numeric_level,
        format=LOG_FORMAT,
        force=True,
    )
