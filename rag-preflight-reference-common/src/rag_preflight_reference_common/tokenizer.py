"""Actionable tiktoken loading for connected and restricted environments."""
import hashlib
import os
from pathlib import Path
from typing import Any

import tiktoken

CL100K_URL = 'https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken'
CL100K_SHA256 = '223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7'
CL100K_CACHE_NAME = hashlib.sha1(CL100K_URL.encode()).hexdigest()


class TokenizerUnavailableError(RuntimeError):
    """The configured tokenizer could not be loaded from cache or its host."""


def encoding_for_model(model: str, *, cache_dir: str | Path | None = None) -> Any:
    """Load the exact tiktoken encoding and explain offline cache recovery.

    The reference applications currently use an OpenAI model mapped to
    ``cl100k_base``. Unknown future mappings still get a useful general error,
    without pretending this package knows their download artifact.
    """
    try:
        return tiktoken.encoding_for_model(model)
    except Exception as exc:
        selected = Path(cache_dir or os.environ.get('TIKTOKEN_CACHE_DIR',
                                                    '~/.cache/tiktoken')).expanduser()
        try:
            encoding_name = tiktoken.encoding_name_for_model(model)
        except Exception:
            encoding_name = None
        if encoding_name == 'cl100k_base':
            destination = selected / CL100K_CACHE_NAME
            message = (
                f"Tokenizer {encoding_name!r} for model {model!r} is not available. "
                f"tiktoken normally downloads cl100k_base.tiktoken from {CL100K_URL}. "
                "If that host is blocked, download the file on an approved connected machine, "
                f"verify SHA-256 {CL100K_SHA256}, copy it to {destination}, and set "
                f"TIKTOKEN_CACHE_DIR={selected} before rerunning. This tokenizer download is "
                "required even for dry-run, but it is not an OpenAI API call."
            )
        else:
            message = (
                f"Tokenizer for model {model!r} could not be loaded. Configure proxy/network "
                f"access or pre-populate the tiktoken cache at {selected} and set "
                "TIKTOKEN_CACHE_DIR before rerunning. The dry run makes no OpenAI API call, "
                "but it requires the tokenizer data."
            )
        raise TokenizerUnavailableError(message) from exc
