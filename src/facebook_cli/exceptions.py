class FacebookCliError(Exception):
    """Base exception for expected CLI failures."""


class AuthenticationError(FacebookCliError):
    """Facebook did not reach an authenticated page."""


class InteractiveAuthenticationRequired(AuthenticationError):
    """Facebook requires a human login in the opened browser."""


class CheckpointChallengeError(FacebookCliError):
    """Facebook opened a checkpoint or challenge page."""


class ElementNotFoundError(FacebookCliError):
    """A required Facebook UI element was not visible."""


class MessengerPinRequiredError(FacebookCliError):
    """Messenger requires a PIN before messages can be accessed."""
