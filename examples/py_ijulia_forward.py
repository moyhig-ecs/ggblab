import json


def handle_payload(payload):
    """Handle an incoming payload from the frontend.

    If a `ggblab_core.handle_payload` function is available it will be
    delegated to; otherwise a simple simulated reply is returned.

    Returns a JSON string (frontend expects `msg.content.data` to be
    a JSON string).
    """
    # Normalize payload: accept JSON string or dict-like
    try:
        if isinstance(payload, str):
            p = json.loads(payload)
        else:
            p = payload
    except Exception:
        p = payload

    # Try to delegate to ggblab_core if present
    try:
        import ggblab_core

        if hasattr(ggblab_core, "handle_payload"):
            reply = ggblab_core.handle_payload(p)
            if isinstance(reply, str):
                return reply
            return json.dumps(reply)
    except Exception:
        # missing ggblab_core or delegation failed; fall through to simulate
        pass

    # Fallback simulation
    t = p.get("type", "") if isinstance(p, dict) else ""
    id_ = p.get("id", None) if isinstance(p, dict) else None
    if t == "function":
        name = p.get("payload", {}).get("name", "")
        value = f"simulated-result-for-{name}"
        reply = {"type": "value", "id": id_, "payload": {"value": value}}
    elif t == "command":
        reply = {"type": "created", "id": id_, "payload": {"label": "A"}}
    else:
        reply = {"type": "error", "id": id_, "payload": {"message": "unsupported type"}}

    return json.dumps(reply)
