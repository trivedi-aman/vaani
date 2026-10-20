"""
Who may use Vaani. There is no sign-up: you decide who gets in.

  - Give someone access: add a line to USERS, then restart the server.
  - Take it away: delete their line and restart. Everyone is signed out on a
    restart, so a removed person cannot stay signed in.

Passwords are stored as salted PBKDF2 hashes, never as plain text, so this
file can be committed and deployed without giving the passwords away. Make a
line for someone with:

    python -m server.users <user_id>

It asks for the password (without showing it) and prints the line to paste.
"""

import getpass
import hashlib
import hmac
import re
import secrets
import sys

ITERATIONS = 600_000
USER_ID = re.compile(r"^[a-z0-9._-]{3,40}$")

# user_id -> password hash. Lowercase user IDs: 3-40 letters, digits, . _ -
USERS: dict[str, str] = {
    "aman": "pbkdf2_sha256$600000$4bd19a2067435862451beeec6fef4b4e$a135d494ec2513a880ea798ea3691a7ae6696ff11f36d424fd03276a281bb983",
    "demo": "pbkdf2_sha256$600000$e78565eb529f4ff0bb06ac2bdf06d743$0ae2ccdefe269b9ff42bbd5d78cb91389f60b0252f8477cfdab3a44e6b11f45b",
}


def hash_password(
    password: str, salt: str | None = None, iterations: int = ITERATIONS
) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), iterations
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


# Checked against when the user ID is unknown, so a wrong ID takes as long as a wrong password.
_DUMMY = hash_password(secrets.token_hex(16))


def check_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        expected = hash_password(password, salt, int(iterations)).split("$")[3]
    except ValueError:
        return False
    return hmac.compare_digest(expected, digest)


def verify(users: dict[str, str], user_id: str, password: str) -> str | None:
    """The canonical user ID if the password is right, else None. Same cost either way."""
    uid = user_id.strip().lower()
    stored = users.get(uid)
    ok = check_password(password, stored or _DUMMY)
    return uid if ok and stored is not None else None


def main() -> None:
    if len(sys.argv) != 2 or not USER_ID.match(sys.argv[1].lower()):
        sys.exit(
            "usage: python -m server.users <user_id>   (3-40 characters: a-z 0-9 . _ -)"
        )
    uid = sys.argv[1].lower()
    password = getpass.getpass(f"Password for {uid}: ")
    if len(password) < 10:
        sys.exit("Use at least 10 characters.")
    if getpass.getpass("Again: ") != password:
        sys.exit("The two passwords differ.")
    print("\nPaste this line into USERS in server/users.py:\n")
    print(f'    "{uid}": "{hash_password(password)}",')


if __name__ == "__main__":
    main()
