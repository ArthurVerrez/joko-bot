"""
Utilities related to Large Language Model interactions.
"""

import warnings
import logging
import time  # Added for timing history
import hashlib  # Added for cache key generation
import os  # Added for cache path
import pickle  # Added for caching
from pathlib import Path
from typing import Any, Dict, Optional, List

import litellm
from litellm import ModelResponse, completion_cost, token_counter
from dotenv import load_dotenv

# Configure logging
logging.getLogger("httpx").setLevel(logging.WARNING)  # hides INFO/DEBUG from httpx
logging.getLogger("httpcore").setLevel(
    logging.WARNING
)  # hides the lower-level transport chatter
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configure LiteLLM
litellm._logging._disable_debugging()
DEFAULT_MODEL = "gemini/gemini-2.5-flash-preview-04-17"

# Create cache directory in the project root
CACHE_DIR = Path(__file__).parent.parent.parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

warnings.filterwarnings(
    "ignore", "Your application has authenticated using end user credentials"
)


class LLMClient:
    """Client for interacting with LLMs via LiteLLM, managing completion history and costs."""

    def __init__(self, default_model: str = DEFAULT_MODEL):
        """Initializes the LLM client and completion history."""
        self.completion_history: List[Dict[str, Any]] = []
        self.default_model = default_model
        # Ensure cache directory exists
        os.makedirs(CACHE_DIR, exist_ok=True)

    def _generate_cache_key(
        self, model: str, messages: List[Dict[str, Any]], **kwargs
    ) -> str:
        """Generates a consistent hash key for caching based on inputs."""
        # Create a stable representation of messages and kwargs
        # Important: Order matters for kwargs, so sort them by key
        stable_input = {
            "model": model,
            "messages": messages,
            "kwargs": sorted(kwargs.items()),
        }
        # Use pickle to serialize the dict, then hash it
        # Using pickle ensures complex structures in messages are handled
        serialized_input = pickle.dumps(stable_input)
        return hashlib.md5(serialized_input).hexdigest()

    def run_completion(
        self, messages: List[Dict[str, Any]], model: str = None, **kwargs
    ) -> Optional[ModelResponse]:
        """
        Executes a LiteLLM completion call, utilizing a local pickle cache.

        If a cached result exists for the exact inputs, it's returned directly.
        Otherwise, executes the completion call via litellm, with retries for rate limit errors.
        Successful, non-cached completion details are logged to the client's history.

        Args:
            messages: The list of messages forming the conversation history/prompt.
            model: Optional model override. If not provided, uses the default model.
            **kwargs: Additional keyword arguments passed to litellm.completion.

        Returns:
            litellm.ModelResponse object on success (from cache or fresh call), or None if an error occurs.
        """
        model = model or self.default_model
        cache_key = self._generate_cache_key(model, messages, **kwargs)
        cache_filename = f"llm_completion_{cache_key}.pkl"
        cache_filepath = CACHE_DIR / cache_filename

        # --- Cache Check ---
        if cache_filepath.exists():
            try:
                with open(cache_filepath, "rb") as f:
                    cached_response = pickle.load(f)
                logger.info(
                    f"Cache hit for LLM completion key {cache_key}. Loading from {cache_filepath}"
                )
                # Return cached result - DO NOT log to history
                return cached_response
            except Exception as e:
                logger.warning(
                    f"Error loading cached LLM completion from {cache_filepath}: {e}. Proceeding with API call.",
                    exc_info=True,
                )
        else:
            logger.info(f"Cache miss for LLM completion key {cache_key}.")

        # --- Execute Completion (Cache Miss) ---
        response: Optional[ModelResponse] = None
        start_time_overall = time.time()  # For overall duration including retries
        error_message = None
        cost = 0.0
        prompt_tokens = 0
        completion_tokens = 0
        success = False

        MAX_RETRIES = 3
        BASE_DEFAULT_RETRY_DELAY = 5  # seconds

        for attempt in range(MAX_RETRIES):
            try:
                logger.debug(
                    f"Calling litellm.completion for model: {model} (kwargs: {kwargs}) - Attempt {attempt + 1}/{MAX_RETRIES}"
                )
                response = litellm.completion(model=model, messages=messages, **kwargs)
                success = True
                logger.debug(
                    f"litellm.completion call successful for model {model} on attempt {attempt + 1}."
                )

                if response:
                    try:
                        cost = completion_cost(completion_response=response)
                        cost = float(cost) if cost is not None else 0.0
                    except Exception as cost_calc_error:
                        logger.warning(
                            f"Could not calculate LiteLLM cost: {cost_calc_error}",
                            exc_info=False,
                        )
                        cost = 0.0

                    if response.usage:
                        prompt_tokens = response.usage.prompt_tokens or 0
                        completion_tokens = response.usage.completion_tokens or 0
                    else:
                        logger.warning("LiteLLM response missing usage data.")

                    log_litellm_usage(
                        response, logger
                    )  # Helper to log details immediately

                break  # Successful attempt, exit retry loop

            except litellm.RateLimitError as rle:
                logger.warning(
                    f"Rate limit error on attempt {attempt + 1}/{MAX_RETRIES} for model {model}. Error: {str(rle)}"
                )
                error_message = str(rle)  # Store the last rate limit error

                if attempt < MAX_RETRIES - 1:
                    retry_after_seconds = None
                    try:
                        # httpx response object is rle.response which should have .json()
                        error_json = rle.response.json()
                        if "details" in error_json and isinstance(
                            error_json["details"], list
                        ):
                            for detail_item in error_json["details"]:
                                if (
                                    isinstance(detail_item, dict)
                                    and detail_item.get("@type")
                                    == "type.googleapis.com/google.rpc.RetryInfo"
                                ):
                                    delay_str = detail_item.get("retryDelay")
                                    if (
                                        delay_str
                                        and isinstance(delay_str, str)
                                        and delay_str.endswith("s")
                                    ):
                                        retry_after_seconds = int(delay_str[:-1])
                                        logger.info(
                                            f"Retrying after {retry_after_seconds}s as specified by API for model {model}."
                                        )
                                        break
                    except Exception as parse_exc:
                        logger.warning(
                            f"Could not parse retryDelay from rate limit error details for model {model}: {parse_exc}"
                        )

                    if retry_after_seconds is None:
                        retry_after_seconds = BASE_DEFAULT_RETRY_DELAY * (
                            2**attempt
                        )  # Exponential backoff
                        logger.info(
                            f"Using default exponential backoff for model {model}: waiting {retry_after_seconds}s."
                        )

                    time.sleep(retry_after_seconds)
                    response = None  # Reset response for the next attempt
                    success = False  # Ensure success is false before next attempt
                else:
                    logger.error(
                        f"Max retries ({MAX_RETRIES}) reached for model {model} due to rate limiting. Last error: {error_message}"
                    )
                    # error_message is already set to the last rle
                    success = False
                    response = None  # Ensure response is None on final failure
                    break  # Exit loop, will proceed to history logging & cache saving section

            except (
                Exception
            ) as e:  # Catch other exceptions not related to rate limiting
                error_message = str(e)
                logger.error(
                    f"Non-retryable error during litellm.completion call for model {model} on attempt {attempt + 1}: {error_message}",
                    exc_info=True,
                )
                success = False
                response = None
                break  # Non-retryable error, exit retry loop

        # Log attempt to history (only if it wasn't a cache hit)
        end_time_overall = time.time()
        duration_overall = end_time_overall - start_time_overall

        self.completion_history.append(
            {
                "timestamp": start_time_overall,
                "model": model,
                "messages": messages,
                "kwargs": kwargs,
                "success": success,  # Final success status after retries
                "error": error_message,  # Final error message
                "response_id": (
                    response.id if response and success else None
                ),  # Guarded access
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_dollars": cost,
                "duration_seconds": duration_overall,  # Use overall duration
                "cached_result_used": False,  # Always False when logged here (cache hits return early)
            }
        )

        # --- Save to Cache (only if successful API call after retries) ---
        if success and response is not None:
            try:
                with open(cache_filepath, "wb") as f:
                    pickle.dump(response, f)
                logger.info(
                    f"Successfully saved LLM completion result to cache: {cache_filepath}"
                )
            except Exception as e:
                logger.error(
                    f"Error saving LLM completion result to cache file {cache_filepath}: {e}",
                    exc_info=True,
                )

        return response

    def get_completion_history_cost(self) -> float:
        """
        Calculates the total cost of non-cached LLM completions executed through this client instance.

        Returns:
            float: The total cost in dollars.
        """
        total_cost = 0.0
        for record in self.completion_history:
            # History only contains non-cached calls
            total_cost += record.get("cost_dollars", 0.0)
        return total_cost

    def get_completion_history_time(self) -> float:
        """
        Calculates the total duration of non-cached LLM completion attempts recorded in the history.

        Returns:
            float: The total duration in seconds.
        """
        total_time = 0.0
        for record in self.completion_history:
            # History only contains non-cached calls
            total_time += record.get("duration_seconds", 0.0)
        return total_time


def log_litellm_usage(response: Any, logger: logging.Logger):
    """
    Logs the cost and token usage information from a LiteLLM completion response.

    Args:
        response: The response object returned by litellm.completion.
        logger: The logger instance to use for output.
    """
    if litellm is None:
        logger.error("LiteLLM library is not installed. Cannot log usage.")
        return

    try:
        # Initialize variables to ensure they exist even if extraction fails
        cost = 0.0
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0

        # Safely access usage data if available
        if response and hasattr(response, "usage") and response.usage:
            input_tokens = getattr(response.usage, "prompt_tokens", 0)
            output_tokens = getattr(response.usage, "completion_tokens", 0)
            total_tokens = getattr(response.usage, "total_tokens", 0)

            # Calculate cost, handling potential errors
            try:
                calculated_cost = completion_cost(completion_response=response)
                # Ensure cost is a float, default to 0.0 if None
                cost = float(calculated_cost) if calculated_cost is not None else 0.0
            except Exception as cost_calc_error:
                logger.warning(
                    f"Could not calculate LiteLLM cost: {cost_calc_error}",
                    exc_info=False,
                )
                cost = 0.0  # Default cost if calculation fails

            # Log the extracted information at INFO level
            logger.info(
                f"LiteLLM call usage - Cost: ${cost:.6f}, "
                f"Prompt Tokens: {input_tokens}, Completion Tokens: {output_tokens}, "
                f"Total Tokens: {total_tokens}"
            )
        else:
            # Log at DEBUG level if usage info is missing, as it might be expected for some models/calls
            logger.debug(
                "LiteLLM response object or usage attribute not found. Cannot log cost/tokens."
            )

    except AttributeError as ae:
        # Log at DEBUG level
        logger.debug(
            f"Attribute error accessing LiteLLM response usage data: {ae}",
            exc_info=False,
        )
    except Exception as e:
        # Catch any other unexpected errors during info extraction
        logger.warning(
            f"Error processing cost/token info from LiteLLM response: {e}",
            exc_info=True,
        )
