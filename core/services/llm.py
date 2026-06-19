"""
LLM integration — NVIDIA NIM API (OpenAI-compatible client, free tier).

Role in platform: personalization + Q&A layer ONLY.
- Never computes CO2 numbers (Python/DB does that).
- Never generates core education content (static EducationContent/GlossaryTerm
  models handle that, written by humans — zero hallucination risk on facts).
- Used for: phrasing a personalized tip from real numbers, and answering
  free-text user questions with real numbers as context.
"""
import re
import logging
from datetime import date
from django.conf import settings
from django.core.cache import cache
from openai import OpenAI

logger = logging.getLogger(__name__)

_client = None


def get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=settings.NVIDIA_API_KEY,
        )
    return _client


FALLBACK_TIP = (
    "We couldn't generate a personalized tip right now. "
    "Check the Learn section for general guidance on reducing emissions "
    "in your highest-impact category."
)

MODEL_NAME = "mistralai/mistral-large-3-675b-instruct-2512"


def _extract_numbers(text):
    return set(re.findall(r"\d+\.?\d*", text))


def _validate_no_invented_numbers(output_text, allowed_numbers):
    """
    Guard against hallucinated figures: every number in the LLM's output
    must appear somewhere in the numbers we gave it as context.
    Returns True if output is safe to show as-is.
    """
    output_numbers = _extract_numbers(output_text)
    invented = output_numbers - allowed_numbers
    if invented:
        logger.warning(f"LLM validation: invented numbers detected: {invented}")
        return False
    return True


def _call_llm(messages):
    """
    Single place for all API calls. Returns (text, error_string).
    error_string is None on success.
    """
    try:
        response = get_client().chat.completions.create(
            model=MODEL_NAME,
            max_tokens=300,
            messages=messages,
        )
        text = response.choices[0].message.content.strip()
        logger.info(f"LLM response received ({len(text)} chars)")
        return text, None
    except Exception as e:
        logger.error(f"LLM API error: {type(e).__name__}: {e}")
        return None, str(e)


def get_education_tip(user, summary: dict, national_avg: dict) -> str:
    """
    summary: {'transport': 45.2, 'energy': 30.0, ...} kg CO2 by category this period
    national_avg: same shape, national average benchmarks
    """
    key = f"tip_{user.id}_{date.today()}"
    cached = cache.get(key)
    if cached:
        logger.info(f"LLM tip served from cache for user {user.id}")
        return cached

    # Build allowed numbers from all numeric values in both dicts
    allowed_numbers = _extract_numbers(str(list(summary.values()))) | \
                      _extract_numbers(str(list(national_avg.values())))

    prompt = (
        f"User's monthly CO2 emissions by category (kg): {summary}\n"
        f"National average benchmarks (kg): {national_avg}\n\n"
        "Write a 2-3 sentence educational explanation of their highest-emission "
        "category and one concrete, low-effort action to reduce it. "
        "Friendly, non-judgmental tone. "
        "Do not state any numeric value that is not given above."
    )

    text, error = _call_llm([{"role": "user", "content": prompt}])
    if error:
        return FALLBACK_TIP

    if not _validate_no_invented_numbers(text, allowed_numbers):
        # One retry with stricter instruction — no numbers at all
        logger.info("LLM validation failed on tip, retrying with no-numbers instruction")
        text, error = _call_llm([{
            "role": "user",
            "content": prompt + "\nIMPORTANT: Do not use any numbers in your answer."
        }])
        if error or not text:
            return FALLBACK_TIP
        # After retry we skip number validation since we asked for no numbers
        # and any slipped-through numbers would be caught by the subset check
        if not _validate_no_invented_numbers(text, allowed_numbers):
            return FALLBACK_TIP

    cache.set(key, text, 60 * 60 * 24)  # 24h TTL
    return text


def answer_question(user, summary: dict, question: str) -> str:
    """
    Free-text Q&A. Rate-limited at the view layer via QAUsage model.
    Not cached (each question is distinct) but bounded by daily call limits.
    """
    # Build allowed numbers from summary values only
    allowed_numbers = _extract_numbers(str(list(summary.values())))

    prompt = (
        f"User's emissions context this month (kg CO2 by category): {summary}\n"
        f"User question: {question}\n\n"
        "Answer in 2-4 sentences, educational tone. "
        "Do not invent or state any numeric value not given above."
    )

    text, error = _call_llm([{"role": "user", "content": prompt}])
    if error:
        logger.error(f"answer_question failed for user {user.id}: {error}")
        return f"Sorry, I couldn't process that question right now. (Error: {error})"

    if not _validate_no_invented_numbers(text, allowed_numbers):
        logger.warning(f"answer_question: invented numbers in response for user {user.id}")
        return (
            "I can't give a precise answer to that without risking inaccurate numbers. "
            "Check the Learn section for general guidance on this topic."
        )

    return text


DAILY_QA_LIMIT = 10


def check_and_increment_qa_usage(user) -> bool:
    """
    Returns True if user is under their daily Q&A limit (and increments usage).
    Returns False if limit reached (caller should block the request).
    """
    from core.models import QAUsage
    today = date.today()
    usage, _ = QAUsage.objects.get_or_create(user=user, date=today)
    if usage.count >= DAILY_QA_LIMIT:
        logger.warning(f"QA rate limit reached for user {user.id} on {today}")
        return False
    usage.count += 1
    usage.save()
    return True