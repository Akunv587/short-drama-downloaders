"""重试工具"""

import asyncio
import functools
import logging
from typing import TypeVar, Callable, Awaitable

logger = logging.getLogger("zaizaimao.retry")

T = TypeVar("T")


def async_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,),
):
    """
    异步重试装饰器

    Args:
        max_retries:     最大重试次数
        base_delay:      初始延迟（秒）
        max_delay:       最大延迟（秒）
        backoff_factor:  退避乘数
        exceptions:      触发重试的异常类型
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt == max_retries:
                        raise
                    delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                    logger.warning(
                        "Retry %d/%d after %.1fs: %s",
                        attempt + 1, max_retries, delay, e,
                    )
                    await asyncio.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
