"""Versioned, deterministic whisper.cpp execution profile."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

PROFILE_VERSION = 1
ENGINE_NAME = "whisper.cpp"


def _scaled(value, name, scale=1000000):
    """Convert a finite decimal value into canonical integer units."""
    if isinstance(value, bool):
        raise ValueError(f"invalid {name}")

    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"invalid {name}") from exc

    if not number.is_finite():
        raise ValueError(f"nonfinite {name}")

    scaled = number * scale

    if scaled != scaled.to_integral_value():
        raise ValueError(f"excess precision: {name}")

    return int(scaled)


def _decimal_argument(value):
    """Render integer micro-units as a stable decimal CLI argument."""
    return format(Decimal(value) / Decimal(1000000), "f")


@dataclass(frozen=True)
class WhisperProfile:
    language: str = "en"
    beam_size: int = 5
    best_of: int = 5
    temperature: float = 0.0
    temperature_increment: float = 0.2
    max_context: int = -1
    audio_context: int = 0
    entropy_threshold: float = 2.4
    logprob_threshold: float = -1.0
    no_speech_threshold: float = 0.6
    initial_prompt: str = ""
    no_fallback: bool = False
    vad: bool = False
    translate: bool = False
    flash_attention: bool = True

    def __post_init__(self):
        if not isinstance(self.language, str) or not self.language.strip():
            raise ValueError("invalid language")

        for name in ("beam_size", "best_of"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"invalid {name}")

        if type(self.max_context) is not int or self.max_context < -1:
            raise ValueError("invalid max_context")

        if type(self.audio_context) is not int or self.audio_context < 0:
            raise ValueError("invalid audio_context")

        for name in (
            "no_fallback", "vad", "translate", "flash_attention"
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"invalid {name}")

        if not isinstance(self.initial_prompt, str):
            raise ValueError("invalid initial_prompt")

        values = {
            "temperature": _scaled(self.temperature, "temperature"),
            "temperature_increment": _scaled(
                self.temperature_increment, "temperature_increment"
            ),
            "entropy_threshold": _scaled(
                self.entropy_threshold, "entropy_threshold"
            ),
            "logprob_threshold": _scaled(
                self.logprob_threshold, "logprob_threshold"
            ),
            "no_speech_threshold": _scaled(
                self.no_speech_threshold, "no_speech_threshold"
            ),
        }

        if not 0 <= values["temperature"] <= 1000000:
            raise ValueError("temperature outside [0,1]")

        if not 0 <= values["temperature_increment"] <= 1000000:
            raise ValueError("temperature increment outside [0,1]")

        if not 0 <= values["no_speech_threshold"] <= 1000000:
            raise ValueError("no-speech threshold outside [0,1]")

    def canonical(self):
        """Return JSON-safe, canonical output-affecting settings."""
        return {
            "profile_version": PROFILE_VERSION,
            "engine": ENGINE_NAME,
            "language": self.language.strip(),
            "beam_size": self.beam_size,
            "best_of": self.best_of,
            "temperature_micro": _scaled(
                self.temperature, "temperature"
            ),
            "temperature_increment_micro": _scaled(
                self.temperature_increment, "temperature_increment"
            ),
            "max_context": self.max_context,
            "audio_context": self.audio_context,
            "entropy_threshold_micro": _scaled(
                self.entropy_threshold, "entropy_threshold"
            ),
            "logprob_threshold_micro": _scaled(
                self.logprob_threshold, "logprob_threshold"
            ),
            "no_speech_threshold_micro": _scaled(
                self.no_speech_threshold, "no_speech_threshold"
            ),
            "initial_prompt": self.initial_prompt,
            "no_fallback": self.no_fallback,
            "vad": self.vad,
            "translate": self.translate,
            "flash_attention": self.flash_attention,
        }

    def cli_arguments(self):
        """Return deterministic whisper-cli options without file paths."""
        if self.vad:
            raise ValueError("VAD requires a separately versioned profile")

        args = [
            "-l", self.language.strip(),
            "-bs", str(self.beam_size),
            "-bo", str(self.best_of),
            "-tp", _decimal_argument(
                _scaled(self.temperature, "temperature")
            ),
            "-tpi", _decimal_argument(
                _scaled(
                    self.temperature_increment,
                    "temperature_increment",
                )
            ),
            "-mc", str(self.max_context),
            "-ac", str(self.audio_context),
            "-et", _decimal_argument(
                _scaled(self.entropy_threshold, "entropy_threshold")
            ),
            "-lpt", _decimal_argument(
                _scaled(self.logprob_threshold, "logprob_threshold")
            ),
            "-nth", _decimal_argument(
                _scaled(self.no_speech_threshold, "no_speech_threshold")
            ),
        ]

        if self.initial_prompt:
            args.extend(["--prompt", self.initial_prompt])

        if self.no_fallback:
            args.append("-nf")

        if self.translate:
            args.append("-tr")

        if not self.flash_attention:
            args.append("-nfa")

        return args

    def canonical_json(self):
        return json.dumps(
            self.canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
