"""
ai/tools/json_filter.py
─────────────────────────────────────────────────────────────────────────────
Tool: JSON Processing Filter Agent

Takes a raw text answer, processes it through an AI filter to extract/format it
as structured JSON, and returns it (and optionally saves it to a JSON file).
─────────────────────────────────────────────────────────────────────────────
"""
import json
import logging
from typing import Any, Dict

from ai.router import call_ai

log = logging.getLogger(__name__)

async def process_answer_to_json(answer_text: str, output_file: str = "answer.json") -> Dict[str, Any]:
    """
    Takes a raw text answer, converts it into a well-structured JSON format
    using an AI agent, and optionally saves it to a file.
    """
    prompt = (
        "You are a structured data processing agent. Your job is to take the following "
        "raw text answer and convert it into a well-structured, valid JSON object. "
        "Extract the key concepts, points, and summary into appropriate JSON keys "
        "(e.g., 'summary', 'key_points', 'details').\n\n"
        "Return ONLY the valid JSON strictly. Do NOT include markdown codeblocks (like ```json), "
        "just the raw JSON string that can be parsed directly by python's json.loads().\n\n"
        f"RAW TEXT ANSWER:\n{answer_text}"
    )

    log.info("Running JSON processing agent...")
    raw_json_str = await call_ai(prompt, max_tokens=2048, temperature=0.1)
    
    # Clean up any potential markdown formatting the AI might have still included
    clean_json_str = raw_json_str.strip()
    if clean_json_str.startswith("```json"):
        clean_json_str = clean_json_str[7:]
    elif clean_json_str.startswith("```"):
        clean_json_str = clean_json_str[3:]
    if clean_json_str.endswith("```"):
        clean_json_str = clean_json_str[:-3]
    
    clean_json_str = clean_json_str.strip()

    try:
        parsed_json = json.loads(clean_json_str)
    except json.JSONDecodeError as e:
        log.error(f"Agent failed to return valid JSON: {e}")
        parsed_json = {
            "error": "Failed to parse JSON from agent.",
            "raw_text": answer_text,
            "raw_agent_output": clean_json_str
        }

    # Write to the json file
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(parsed_json, f, indent=4)
        log.info(f"JSON answer successfully saved to {output_file}")
    except Exception as e:
        log.error(f"Could not write to JSON file: {e}")

    return parsed_json
