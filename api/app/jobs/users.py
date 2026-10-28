"""User admin CLI: `python -m app.jobs.users create|set-password|deactivate|list`."""

import argparse
import getpass
import sys

from sqlalchemy import select

from app.db import SessionLocal, get_engine
from app.models.user import User
from app.services import auth


def _prompt_password() -> str:
    password = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != password:
        sys.exit("Passwords don't match")
    error = auth.password_error(password)
    if error:
        sys.exit(error)
    return password


def _email(raw: str) -> str:
    email = auth.normalise_email(raw)
    if not auth.is_valid_email(email):
        sys.exit("Enter a valid email address")
    return email


def create(email: str) -> None:
    email = _email(email)
    with SessionLocal() as session:
        if auth.get_user_by_email(session, email) is not None:
            sys.exit(f"User {email} already exists (use set-password)")
        password = _prompt_password()
        session.add(User(email=email, password_hash=auth.hash_password(password)))
        session.commit()
    print(f"Created {email}")


def set_password(email: str) -> None:
    email = _email(email)
    with SessionLocal() as session:
        user = auth.get_user_by_email(session, email)
        if user is None:
            sys.exit(f"No user {email}")
        user.password_hash = auth.hash_password(_prompt_password())
        session.commit()
    print(f"Password updated for {email}")


def deactivate(email: str) -> None:
    email = _email(email)
    with SessionLocal() as session:
        user = auth.get_user_by_email(session, email)
        if user is None:
            sys.exit(f"No user {email}")
        user.is_active = False
        session.commit()
    print(f"Deactivated {email}")


def list_users() -> None:
    with SessionLocal() as session:
        for user in session.scalars(select(User).order_by(User.id)):
            state = "active" if user.is_active else "inactive"
            password = "password" if user.password_hash else "no password"
            print(f"{user.id}\t{user.email}\t{state}\t{password}\tlast_login={user.last_login_at}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.jobs.users")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "set-password", "deactivate"):
        commands.add_parser(name).add_argument("--email", required=True)
    commands.add_parser("list")
    args = parser.parse_args()

    get_engine()
    if args.command == "create":
        create(args.email)
    elif args.command == "set-password":
        set_password(args.email)
    elif args.command == "deactivate":
        deactivate(args.email)
    else:
        list_users()


if __name__ == "__main__":
    main()
