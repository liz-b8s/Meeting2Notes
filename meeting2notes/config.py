"""
Configuration constants for meeting2notes.
These were extracted from the original monolithic script to keep
configuration and defaults in one place.
"""

from __future__ import annotations

OPENAI_BASE_URL = "https://api.openai.com/v1"
CHAT_MODEL = "gpt-4.1-mini"

DEFAULT_WHISPER_MODEL = "small"
DEFAULT_CHUNK_SECONDS = 600          # chunk size in seconds (10 minutes)
AUTO_CHUNK_IF_LONGER_THAN_S = 600    # if meeting > 10 minutes, chunk it
TRANSCRIPTION_GBP_PER_MIN = 0.0      # local => £0.00

# Pricing for chat calls (GBP)
PRICING_GBP = {
    "gpt-4.1-mini": {"input_per_1k": 0.00015, "output_per_1k": 0.00060},
    "gpt-4.1": {"input_per_1k": 0.0025, "output_per_1k": 0.0100},
}
