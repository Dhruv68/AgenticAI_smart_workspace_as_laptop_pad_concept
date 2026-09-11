"""Desktop agent: a tool-calling loop over Ollama's /api/chat.

Agent mode is the "do things" path (web search, Gmail, notes, browser);
the plain circle-ask path stays a fast single vision call. The loop runs
at most MAX_STEPS model -> tool -> model turns, then returns the final text.
"""

from __future__ import annotations

AGENT_SYSTEM_PROMPT = """You are the desktop agent inside the user's smart \
workspace app. You can act on the user's computer through tools: search the \
web, open pages in the app's browser tab, read and search Gmail, and save or \
search the user's local notes.

Rules:
- Use tools when the user asks about the web, email, or their notes. Answer \
directly from your own knowledge otherwise.
- Chain tools when needed (e.g. web_search, then browser_open the best \
result), but don't call tools just to look busy.
- gmail_send ALWAYS asks the user for confirmation first — just call it with \
the draft; the app handles the confirmation.
- Keep final answers concise and concrete, like a helpful margin note.
- If a tool reports an error (Gmail not connected, no results), say so \
plainly and suggest the fix.
"""

MAX_STEPS = 5


class AgentRunner:
    """Runs the tool-calling loop. Blocking — call from a worker thread."""

    def __init__(self, client, registry, max_steps: int = MAX_STEPS) -> None:
        self._client = client
        self._registry = registry
        self._max_steps = max_steps

    def run(
        self,
        user_text: str,
        image_png: bytes | None = None,
        progress_cb=None,
        confirm_fn=None,
    ) -> str:
        """Run the loop; return the final answer text.

        *progress_cb* receives human-readable step updates ("searching the
        web…"). *confirm_fn* is called with a draft dict for gated tools and
        must return True/False (blocks the worker thread while the UI asks).
        """
        from ..tools import NeedsConfirmation

        user_msg: dict = {"role": "user", "content": user_text.strip()}
        if image_png:
            import base64

            user_msg["images"] = [base64.b64encode(image_png).decode("ascii")]
        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            user_msg,
        ]
        tools = self._registry.ollama_tools()

        def progress(text: str) -> None:
            if progress_cb:
                try:
                    progress_cb(text)
                except Exception:
                    pass

        for _ in range(self._max_steps):
            message = self._client.chat(messages, tools=tools)
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                answer = (message.get("content") or "").strip()
                return answer or "The model returned an empty response."

            messages.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                func = call.get("function", {})
                name = func.get("name", "")
                args = func.get("arguments", {}) or {}
                if isinstance(args, str):
                    try:
                        import json

                        args = json.loads(args) if args.strip() else {}
                    except Exception:
                        args = {}
                progress(f"using {name}…")
                try:
                    result = self._registry.call(name, args)
                except NeedsConfirmation as nc:
                    approved = confirm_fn(nc.draft) if confirm_fn else False
                    if approved:
                        progress(f"confirmed — running {name}…")
                        try:
                            result = self._registry.call(
                                name, {**nc.draft, "_confirmed": True}
                            )
                        except Exception as exc:
                            result = f"Tool {name} failed after confirmation: {exc}"
                    else:
                        result = (
                            f"User did NOT approve {name}; it was not executed. "
                            "Tell the user what you wanted to do and stop."
                        )
                except KeyError:
                    result = f"Unknown tool '{name}'."
                except TypeError as exc:
                    result = f"Tool {name} got bad arguments: {exc}"
                except Exception as exc:
                    result = f"Tool {name} failed: {exc}"
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": name,
                        "content": str(result)[:12000],
                    }
                )

        return (
            "I ran out of steps before finishing. "
            "Try asking in a smaller piece."
        )
