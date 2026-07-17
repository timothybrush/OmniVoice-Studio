"""A model load interrupted by interpreter shutdown must be recognised as a
benign teardown, not logged as a crash.

When the backend is torn down mid-load (uvicorn stopping, a failed port bind,
or the user closing the app while the model loads), transformers' materializer
raises ``RuntimeError: cannot schedule new futures after interpreter shutdown``
from its own thread pool. That used to surface as a scary "Model loading
failed" error + full traceback in the crash report. `_is_interpreter_shutdown_error`
classifies it so the loader can log it calmly instead. See model_manager.py.
"""

from services.model_manager import _is_interpreter_shutdown_error


def test_direct_interpreter_shutdown_runtimeerror():
    exc = RuntimeError("cannot schedule new futures after interpreter shutdown")
    assert _is_interpreter_shutdown_error(exc) is True


def test_shutdown_error_wrapped_in_cause_chain():
    # transformers wraps the original error several layers deep.
    root = RuntimeError("cannot schedule new futures after interpreter shutdown")
    try:
        try:
            raise root
        except RuntimeError as e:
            raise ImportError("Could not import module OmniVoice") from e
    except ImportError as wrapped:
        assert _is_interpreter_shutdown_error(wrapped) is True


def test_shutdown_error_via_implicit_context():
    root = RuntimeError("cannot schedule new futures after interpreter shutdown")
    try:
        try:
            raise root
        except RuntimeError:
            raise ValueError("secondary")  # sets __context__, not __cause__
    except ValueError as chained:
        assert _is_interpreter_shutdown_error(chained) is True


def test_plain_pool_shutdown_is_not_interpreter_shutdown():
    # A single pool being reset ("after shutdown", no "interpreter") is a real
    # fault we must NOT silence.
    exc = RuntimeError("cannot schedule new futures after shutdown")
    assert _is_interpreter_shutdown_error(exc) is False


def test_unrelated_error_is_not_shutdown():
    assert _is_interpreter_shutdown_error(OSError("disk full")) is False
    assert _is_interpreter_shutdown_error(None) is False


def test_cause_cycle_terminates():
    # A self-referential cause chain must not loop forever.
    a = RuntimeError("a")
    b = RuntimeError("b")
    a.__cause__ = b
    b.__cause__ = a
    assert _is_interpreter_shutdown_error(a) is False
