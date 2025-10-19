#!/usr/bin/env python3
# register_users.py
import argparse
import os
from getpass import getpass
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

# Import your existing User model from models.py
from models import User, db

# --------------------------------------------------------------------
# Database connection
# --------------------------------------------------------------------
SUPABASE_DATABASE_URL = os.getenv("SUPABASE_DATABASE_URL")

if not SUPABASE_DATABASE_URL:
    raise RuntimeError("❌ Missing SUPABASE_DATABASE_URL in your environment (.env) file.")

# Make sure it’s the SQLAlchemy-compatible format
if SUPABASE_DATABASE_URL.startswith("postgresql://") and "psycopg2" not in SUPABASE_DATABASE_URL:
    SUPABASE_DATABASE_URL = SUPABASE_DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")

engine = create_engine(SUPABASE_DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


# --------------------------------------------------------------------
# Helper functions
# --------------------------------------------------------------------
def user_exists(sess, username=None, email=None):
    """Check if a user already exists by username or email."""
    if username:
        if sess.execute(select(User.id).where(User.username == username)).scalar():
            return "username"
    if email:
        if sess.execute(select(User.id).where(User.email == email)).scalar():
            return "email"
    return None


def create_user(sess, username: str, email: str, password: str):
    """Create a new user with hashed password."""
    hashed = generate_password_hash(password)
    u = User(username=username, email=email.lower(), password_hash=hashed)
    sess.add(u)
    sess.commit()
    sess.refresh(u)
    return u


# --------------------------------------------------------------------
# Main logic
# --------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Create users directly in the Supabase database.")
    parser.add_argument("--username", "-u", help="Username (required).")
    parser.add_argument("--email", "-e", help="Email (required).")
    parser.add_argument("--password", "-p", help="Password (optional; will prompt if not provided).")
    args = parser.parse_args()

    username = (args.username or "").strip()
    email = (args.email or "").strip().lower()
    password = args.password

    if not username:
        username = input("Username: ").strip()
    if not email:
        email = input("E-mail: ").strip().lower()
    if not password:
        while True:
            p1 = getpass("Password: ")
            p2 = getpass("Confirm password: ")
            if p1 != p2:
                print("Passwords do not match. Try again.")
            elif not p1:
                print("Password cannot be empty.")
            else:
                password = p1
                break

    # Run creation
    with SessionLocal() as sess:
        dup = user_exists(sess, username=username, email=email)
        if dup == "username":
            print(f"❌ Error: username '{username}' already exists.")
            return
        if dup == "email":
            print(f"❌ Error: email '{email}' already exists.")
            return

        try:
            u = create_user(sess, username=username, email=email, password=password)
            print(f"✅ User created successfully!")
            print(f"   ID: {u.id}")
            print(f"   Username: {u.username}")
            print(f"   Email: {u.email}")
        except IntegrityError:
            sess.rollback()
            print("❌ Integrity error: duplicated username or email.")


if __name__ == "__main__":
    main()
