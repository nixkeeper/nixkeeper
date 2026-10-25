"""The one exception nixkeeper raises for a problem its user has to fix."""


class Problem(Exception):
    """A problem the person running nixkeeper has to fix, with what to say.

    Library code raises it instead of exiting, so a caller that can carry on
    without the missing piece (notify, without the package lists) catches it
    and goes on. Only the command (cli.main) turns it into an exit, printing
    the message.
    """
