"""Expected model setup failures shared by accounting and generation paths."""


class LocalModelSnapshotUnavailable(RuntimeError):
    """A configured local snapshot is absent or incomplete; no download is made."""

    code = "local_model_setup_required"
    public_message = (
        "The selected local model is unavailable or incomplete. Complete model "
        "setup, then retry your question. No automatic download was attempted."
    )
