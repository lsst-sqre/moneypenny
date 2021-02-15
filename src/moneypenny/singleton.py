# Stolen from
# https://stackoverflow.com/questions/6760685/creating-a-singleton-in-python
from typing import Any, Dict


class Singleton(type):
    """Singleton metaclass.  Create a Singleton class with:
    Class Foo(metaclass=Singleton)
    """

    _instances: Dict[Any, Any] = {}

    def __call__(cls, *args, **kwargs) -> Dict[Any, Any]:  # type: ignore
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(
                *args, **kwargs
            )
        return cls._instances[cls]
