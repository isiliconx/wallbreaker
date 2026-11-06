"""rootaccess: client-ready LLM red-team runner. Batteries + ladders + disguises + dual judges."""
from .runner import run_campaign
from .judges import canary_score, lane_of
from .disguises import MUTATE_STRATEGIES, mutate_prompt

__all__ = ["run_campaign", "canary_score", "lane_of", "MUTATE_STRATEGIES", "mutate_prompt"]
__version__ = "1.0.0"
