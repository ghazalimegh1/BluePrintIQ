from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import ValidationError

from .schemas import LLMProviderConfig, QuestionSpec
from .tools import ENTITY_TERMS, interpret_question, tool_registry


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)


class InterpreterError(RuntimeError):
    """A configured structured-question provider failed or returned invalid data."""


def configured_provider(
    provider: LLMProviderConfig | None = None,
) -> LLMProviderConfig | None:
    if provider is None:
        return None
    if provider.provider != "groq":
        raise InterpreterError("The selected LLM provider is not supported.")
    if not os.getenv("GROQ_API_KEY"):
        raise InterpreterError(
            "Set GROQ_API_KEY in the backend environment or ignored .env file."
        )
    model = os.getenv("GROQ_MODEL", "").strip() or provider.model.strip()
    if not model:
        raise InterpreterError("Set GROQ_MODEL or select a model in the UI.")
    return LLMProviderConfig(provider="groq", model=model)


def _call_chat_completions(
    provider: LLMProviderConfig, body: dict[str, Any]
) -> dict[str, Any]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise InterpreterError(
            "Set GROQ_API_KEY in the backend environment or ignored .env file."
        )
    try:
        from groq import (
            APIConnectionError,
            APIError,
            APIStatusError,
            APITimeoutError,
            Groq,
            RateLimitError,
        )
    except ImportError as exc:
        raise InterpreterError(
            "The Groq Python SDK is missing; install the project requirements."
        ) from exc

    client = Groq(api_key=api_key, timeout=30.0, max_retries=2)
    try:
        response = client.chat.completions.create(
            model=provider.model,
            **{key: value for key, value in body.items() if key != "model"},
        )
    except RateLimitError as exc:
        raise InterpreterError("Groq rate limit reached after SDK retries; retry later.") from exc
    except APITimeoutError as exc:
        raise InterpreterError("Groq request timed out after SDK retries.") from exc
    except APIConnectionError as exc:
        raise InterpreterError("Could not connect to Groq after SDK retries.") from exc
    except APIStatusError as exc:
        raise InterpreterError(f"Groq returned HTTP {exc.status_code}.") from exc
    except APIError as exc:
        raise InterpreterError("Groq request failed in the SDK.") from exc

    try:
        result = response.model_dump()
    except (AttributeError, TypeError, ValueError) as exc:
        raise InterpreterError("Groq returned an invalid response object.") from exc
    if not isinstance(result, dict):
        raise InterpreterError("Groq returned an invalid response object.")
    return result


def _planning_tool(allowed_tools: list[str]) -> dict[str, Any]:
    if not allowed_tools:
        raise InterpreterError("No compatible registered tools are available for this format.")
    return {
        "type": "function",
        "function": {
            "name": "plan_document_question",
            "description": (
                "Interpret a construction document question and select one or more "
                "registered tools for the selected document format. Do not answer the question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["count", "measure", "find_text", "calculate", "describe"],
                    },
                    "question_type": {
                        "type": "string",
                        "enum": ["count", "area", "length", "volume", "text", "other"],
                    },
                    "intent": {
                        "type": "string",
                        "enum": ["count", "measure", "retrieve", "aggregate", "compare", "summarize", "describe"],
                    },
                    "entity_concepts": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(ENTITY_TERMS)},
                    },
                    "recommended_tools": {
                        "type": "array",
                        "items": {"type": "string", "enum": allowed_tools},
                        "minItems": 1,
                        "maxItems": 3,
                    },
                    "scope": {"type": ["string", "null"]},
                    "output_unit": {"type": ["string", "null"]},
                    "ambiguities": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "operation",
                    "entity_concepts",
                    "recommended_tools",
                    "scope",
                    "output_unit",
                    "ambiguities",
                ],
                "additionalProperties": False,
            },
        },
    }


def interpret_with_provider(
    question: str,
    provider: LLMProviderConfig | None = None,
    *,
    allowed_tools: list[str] | None = None,
) -> tuple[QuestionSpec, str]:
    selected_provider = configured_provider(provider)
    if selected_provider is None:
        return interpret_question(question), "deterministic"

    candidate_tools = (
        allowed_tools
        if allowed_tools is not None
        else [spec.name for spec in tool_registry()]
    )
    tool = _planning_tool(candidate_tools)
    tool_context = [
        {
            "name": item.name,
            "operations": item.operations,
            "formats": item.input_formats,
            "description": item.description,
            "limitations": item.limitations,
        }
        for item in tool_registry()
        if item.name in candidate_tools
    ]
    body = {
        "temperature": 0,
        "max_completion_tokens": 500,
        "tools": [tool],
        "tool_choice": {
            "type": "function",
            "function": {"name": "plan_document_question"},
        },
        "messages": [
            {
                "role": "system",
                "content": (
                    "Create a validated execution plan for a construction-document question. "
                    "Select only the supplied tools, based on the document format and question. "
                    "Do not answer the question or invent capabilities. Registered tool details: "
                    f"{json.dumps(tool_context)}"
                ),
            },
            {"role": "user", "content": question},
        ],
    }
    response_body = _call_chat_completions(selected_provider, body)

    try:
        message = response_body["choices"][0]["message"]
        tool_calls = message["tool_calls"]
        if not isinstance(tool_calls, list) or not tool_calls:
            raise ValueError("provider did not return a tool call")
        function_call = tool_calls[0]["function"]
        if function_call["name"] != "plan_document_question":
            raise ValueError("provider selected an unregistered planning function")
        arguments = function_call["arguments"]
        parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        if not isinstance(parsed, dict):
            raise ValueError("provider plan is not an object")
        allowed_concepts = set(ENTITY_TERMS)
        concepts = parsed.get("entity_concepts", [])
        if not isinstance(concepts, list) or any(
            not isinstance(concept, str) or concept not in allowed_concepts
            for concept in concepts
        ):
            raise ValueError("provider returned an unregistered entity concept")
        selected_tools = parsed.get("recommended_tools")
        if (
            not isinstance(selected_tools, list)
            or not selected_tools
            or any(
                not isinstance(name, str) or name not in candidate_tools
                for name in selected_tools
            )
        ):
            raise ValueError("provider selected an unavailable or unregistered tool")
        parsed["original_question"] = question
        # Older/plainer planners may omit the new metadata. Derive it locally
        # rather than rejecting an otherwise valid plan.
        local_spec = interpret_question(question)
        parsed.setdefault("question_type", local_spec.question_type)
        parsed.setdefault("intent", local_spec.intent)
        spec = QuestionSpec.model_validate(parsed)
        tool_operations = {
            item.name: set(item.operations)
            for item in tool_registry()
            if item.name in candidate_tools
        }
        if any(parsed["operation"] not in tool_operations[name] for name in selected_tools):
            raise ValueError("provider selected a tool that does not support the planned operation")
        detectors = {
            "grounding_dino_detection",
            "cubicasa_floorplan_segmentation",
        } & set(selected_tools)
        if len(detectors) > 1:
            raise ValueError("provider selected multiple competing object detectors")
        if "sam2_instance_segmentation" in selected_tools and (
            "grounding_dino_detection" not in detectors
        ):
            raise ValueError("SAM 2 requires a Grounding DINO detection prompt")
        if "gemini_vl_semantic_review" in selected_tools and (
            "grounding_dino_detection" not in detectors
        ):
            raise ValueError("Gemini semantic review requires Grounding DINO candidates")
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        ValidationError,
        json.JSONDecodeError,
    ) as exc:
        raise InterpreterError("Groq returned an invalid structured execution plan.") from exc
    return spec, f"groq:{selected_provider.model}"
