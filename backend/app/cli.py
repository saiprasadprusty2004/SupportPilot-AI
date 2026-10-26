import argparse
import getpass
import os
import secrets


def main():
    parser = argparse.ArgumentParser(description="SupportPilot administration")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Start a local-only SQLite demo with an in-process dispatcher")
    demo.add_argument("--port", type=int, default=8000)
    bootstrap = sub.add_parser("bootstrap", help="Create an initial owner and workspace after migrations")
    bootstrap.add_argument("--email", required=True)
    bootstrap.add_argument("--name", default="Workspace owner")
    bootstrap.add_argument("--workspace", default="My workspace")
    sub.add_parser("generate-secrets", help="Print fresh secret values; save securely in your .env")
    sub.add_parser("setup-checkpoints", help="Provision LangGraph tables using the worker role")
    args = parser.parse_args()
    if args.command == "generate-secrets":
        from cryptography.fernet import Fernet

        print("SECRET_KEY=" + secrets.token_urlsafe(48))
        print("ENCRYPTION_KEY=" + Fernet.generate_key().decode())
        return
    if args.command == "demo":
        os.environ["DEMO_MODE"] = "true"
        os.environ.setdefault("APP_URL", "http://localhost:5173")
        import uvicorn

        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, access_log=False)
    elif args.command == "setup-checkpoints":
        from app.services.jobs import checkpointer

        with checkpointer() as saver:
            saver.setup()
    else:
        from email_validator import validate_email
        from sqlalchemy import select
        from app.db import session_scope
        from app.models import Membership, User, Workspace
        from app.security import passwords

        password = getpass.getpass("Owner password (12+ characters): ")
        if len(password) < 12:
            raise SystemExit("Password must contain at least 12 characters")
        email = validate_email(args.email, check_deliverability=False).normalized.lower()
        with session_scope(worker=True) as db:
            if db.scalar(select(User.id).where(User.email == email)):
                raise SystemExit("Account already exists")
            user = User(email=email, name=args.name, password_hash=passwords.hash(password))
            workspace = Workspace(name=args.workspace)
            db.add_all([user, workspace])
            db.flush()
            db.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
        print("Owner and workspace created. Sign in through the dashboard.")


if __name__ == "__main__":
    main()
