"""Providers package - implement your own provider by extending BaseProvider."""

from .base import BaseProvider, ProviderConfig
from .lmstudio import LMStudioProvider
from .nvidia_nim import NvidiaNimProvider
from .open_router import OpenRouterProvider
from .exceptions import (
    ProviderError,
    AuthenticationError,
    InvalidRequestError,
    RateLimitError,
    OverloadedError,
    APIError,
)

__all__ = [
    "BaseProvider",
    "ProviderConfig",
    "LMStudioProvider",
    "NvidiaNimProvider",
    "OpenRouterProvider",
    "ProviderError",
    "AuthenticationError",
    "InvalidRequestError",
    "RateLimitError",
    "OverloadedError",
    "APIError",
]
