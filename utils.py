import string
import secrets

ALPHABET = string.ascii_letters + string.digits  # a-z, A-Z, 0-9 (base62)


def generate_short_code(length=6):
    return ''.join(secrets.choice(ALPHABET) for _ in range(length))