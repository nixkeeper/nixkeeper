"""Run a slow source in the background while the sync asks the others.

The sync (sync.py) asks Hydra this way. Each server is still asked one
request at a time, as before: only the waiting overlaps.
"""

import threading


class Background:
    """A function call running in a thread of its own, started at once.

    The thread is a daemon, so a sync that stops early (sys.exit) doesn't
    wait for it.

    Args:
        fn: The function to call.
        *args: Its arguments.
    """

    def __init__(self, fn, *args):
        self._value = self._error = None
        self._thread = threading.Thread(target=self._run, args=(fn, args), daemon=True)
        self._thread.start()

    def _run(self, fn, args):
        try:
            self._value = fn(*args)
        except BaseException as e:  # raised again in result()
            self._error = e

    def done(self):
        """Whether the call has finished, without waiting for it."""
        return not self._thread.is_alive()

    def result(self):
        """Wait for the call to finish, and give its result.

        Returns:
            What the function returned.

        Raises:
            Whatever the function raised, raised again here. It's the same
            exception object, so its traceback still points into the thread
            (where a Hydra failure happened, say).
        """
        self._thread.join()
        if self._error is not None:
            raise self._error
        return self._value
