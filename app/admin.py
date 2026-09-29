import argparse
from getpass import getpass

from sqlalchemy import select

from .database import Base, SessionLocal, engine
from .models import User, UserSession
from .security import hash_password, validate_password, validate_username

INITIAL_SUPERADMIN_USERNAME = "wangxueqin"


def read_password() -> str:
    password = getpass("Password (at least 14 characters): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match.")
    validate_password(password)
    return password


def read_initial_password() -> str:
    print("This one-time initialization command accepts the requested initial password without the normal minimum-length rule.")
    password = getpass("Initial superadmin password: ")
    confirmation = getpass("Confirm initial superadmin password: ")
    if not password:
        raise ValueError("Password cannot be empty.")
    if password != confirmation:
        raise ValueError("Passwords do not match.")
    return password


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage certificate manager login accounts.")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin", help="Create an application administrator")
    create.add_argument("username", nargs="?")
    reset = commands.add_parser("reset-password", help="Reset an existing administrator password")
    reset.add_argument("username")
    commands.add_parser("initialize-superadmin", help="One-time initialization for the first local superadmin account")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if args.command == "create-admin":
            username = args.username or input("Username (3–50 letters, digits, dot, underscore or hyphen): ").strip()
            validate_username(username)
            if db.scalar(select(User.id).where(User.username == username)):
                raise ValueError("That username already exists.")
            password = read_password()
            db.add(User(username=username, password_hash=hash_password(password), is_active=True))
            db.commit()
            print(f"Administrator {username!r} created. Start the API service when ready.")
        elif args.command == "reset-password":
            user = db.scalar(select(User).where(User.username == args.username))
            if user is None:
                raise ValueError("Administrator not found.")
            user.password_hash = hash_password(read_password())
            db.query(UserSession).filter(UserSession.user_id == user.id).delete(synchronize_session=False)
            db.commit()
            print(f"Password reset for {args.username!r}; all existing sessions were revoked.")
        elif args.command == "initialize-superadmin":
            validate_username(INITIAL_SUPERADMIN_USERNAME)
            users = db.scalars(select(User).order_by(User.id)).all()
            if not users:
                user = User(username=INITIAL_SUPERADMIN_USERNAME, password_hash="", is_active=True)
                db.add(user)
            elif len(users) == 1 and users[0].username == "admin":
                user = users[0]
                user.username = INITIAL_SUPERADMIN_USERNAME
                user.is_active = True
            else:
                raise ValueError("This is only for a new database or the default single 'admin' account; no changes were made.")
            password = read_initial_password()
            user.password_hash = hash_password(password)
            db.flush()
            db.query(UserSession).filter(UserSession.user_id == user.id).delete(synchronize_session=False)
            db.commit()
            print(f"Initial superadmin {INITIAL_SUPERADMIN_USERNAME!r} is ready; all previous sessions were revoked.")
    except ValueError as exc:
        db.rollback()
        parser.error(str(exc))
    finally:
        db.close()


if __name__ == "__main__":
    main()
