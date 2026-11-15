"""Bounded Responses API transport; only the same scoped Drive tool is exposed."""
import json
from .registry import Denied, Uncertain


def respond_responses(text, executor, config, client):
    from .worker import scoped_tool, instructions
    function = scoped_tool(config)["function"]
    tool = {"type": "function", **function}
    items = [{"role": "user", "content": text}]
    for _ in range(8):
        stream = client.responses.create(model=config["model"], instructions=instructions(config),
            input=items, tools=[tool], tool_choice="auto", store=False, stream=True)
        response = None
        try:
            for event in stream:
                if event.type == "response.completed":
                    response = event.response
                elif event.type in {"response.failed", "response.incomplete", "error"}:
                    raise Uncertain("Model response failed or was incomplete.")
        finally:
            stream.close()
        if response is None:
            raise Uncertain("No completed model response.")
        output = [item.model_dump(exclude_none=True) for item in response.output]
        if len(json.dumps(output)) > 262144:
            raise Uncertain("Model response exceeds budget.")
        calls = [item for item in output if item.get("type") == "function_call"]
        if not calls:
            executor.recheck()
            text = "".join(part.get("text", "") for item in output if item.get("type") == "message"
                           for part in item.get("content", []) if part.get("type") == "output_text")
            return text or "No result."
        if len(calls) > 4:
            raise Uncertain("Tool budget exceeded.")
        items.extend(output)
        for call in calls:
            if call.get("name") != "scoped_drive":
                raise Denied("Unknown tool.")
            value = executor.execute(json.loads(call["arguments"]))
            items.append({"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps(value)})
    raise Uncertain("Request budget exceeded.")
