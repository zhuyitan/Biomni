"""
Simple agent using the openai base package pointed at Argonne's Argo Gateway API.

Argo is an OpenAI-compatible LLM gateway for Argonne National Laboratory.
  Chat endpoint : https://apps.inside.anl.gov/argoapi/v1/chat/completions
  Authentication: pass your ANL domain username as the api_key
  Model names   : gpt4o | gpt41 | gpt54 | gpt5 | gpt41mini | ... (see Argo docs)

The agent loop here is hand-rolled (no SDK framework):
  1. Send messages + tool definitions to the model.
  2. If the model calls a tool, execute it and append the result.
  3. Repeat until the model returns a plain text answer.
"""

import json
import os

from openai import OpenAI

# ---------------------------------------------------------------------------
# Argo connection
# ---------------------------------------------------------------------------
ARGO_BASE_URL = "https://apps.inside.anl.gov/argoapi/v1"
ARGO_USER = os.environ.get("ARGO_USER", "yitan.zhu")   # ANL domain username
ARGO_MODEL = os.environ.get("ARGO_MODEL", "gpt4o")     # Argo model name

client = OpenAI(base_url=ARGO_BASE_URL, api_key=ARGO_USER)

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling schema)
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add",
            "description": "Add two numbers together.",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"},
                },
                "required": ["a", "b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dna_complement",
            "description": "Return the reverse complement of a DNA sequence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sequence": {
                        "type": "string",
                        "description": "DNA sequence (A/T/C/G, case-insensitive)",
                    }
                },
                "required": ["sequence"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def add(a: float, b: float) -> str:
    return str(a + b)


def get_dna_complement(sequence: str) -> str:
    table = str.maketrans("ATCGatcg", "TAGCtagc")
    return sequence.translate(table)[::-1]


TOOL_REGISTRY = {
    "add": add,
    "get_dna_complement": get_dna_complement,
}


def call_tool(name: str, arguments: str) -> str:
    kwargs = json.loads(arguments)
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return f"Error: unknown tool '{name}'"
    return fn(**kwargs)


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
def run_agent(user_prompt: str, system: str = "You are a helpful assistant.") -> str:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]

    print(f"\n{'='*60}")
    print(f"User: {user_prompt}")
    print(f"{'='*60}")

    while True:
        response = client.chat.completions.create(
            model=ARGO_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        message = response.choices[0].message

        # No tool calls — final answer
        if not message.tool_calls:
            print(f"\nAssistant: {message.content}")
            return message.content

        # Append the assistant turn (with tool_calls)
        messages.append(message)

        # Execute each requested tool and append results
        for tc in message.tool_calls:
            result = call_tool(tc.function.name, tc.function.arguments)
            print(f"  [tool] {tc.function.name}({tc.function.arguments}) -> {result}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                }
            )


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_agent("What is 17 plus 38?")
    run_agent("What is the reverse complement of the DNA sequence ATCGGTAC?")
    run_agent("What is the reverse complement of ATCGGTAC, and what is 100 plus that sequence's length?")
