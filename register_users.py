#!/usr/bin/env python3
# register_users.py
import argparse
import os
from getpass import getpass
from pathlib import Path

from sqlalchemy import Column, Integer, String, create_engine, select, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

# Resolve o diretório do projeto (este arquivo vive dentro de Web/)
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SQLITE = f"sqlite:///{(BASE_DIR / 'instance' / 'web.db').as_posix()}"

# Usa o mesmo banco do app por padrão: instance/web.db
DATABASE_URL = os.getenv('DATABASE_URL', DEFAULT_SQLITE)

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=False, unique=True, index=True)
    email = Column(String(120), nullable=False, unique=True, index=True)
    password_hash = Column(String(128), nullable=False)

    __table_args__ = (
        UniqueConstraint('username', name='uq_users_username'),
        UniqueConstraint('email', name='uq_users_email'),
    )

def ensure_tables():
    Base.metadata.create_all(engine)

def user_exists(sess, username=None, email=None):
    if username:
        if sess.execute(select(User.id).where(User.username == username)).scalar():
            return 'username'
    if email:
        if sess.execute(select(User.id).where(User.email == email)).scalar():
            return 'email'
    return None

def create_user(sess, username: str, email: str, password: str):
    hashed = generate_password_hash(password)
    u = User(username=username, email=email.lower(), password_hash=hashed)
    sess.add(u)
    sess.commit()
    sess.refresh(u)
    return u

def main():
    parser = argparse.ArgumentParser(description='Cria usuários na base do site (instance/web.db por padrão).')
    parser.add_argument('--username', '-u', help='Username (obrigatório).')
    parser.add_argument('--email', '-e', help='E-mail (obrigatório).')
    parser.add_argument('--password', '-p', help='Senha (opcional; se não informado, será solicitado).')
    args = parser.parse_args()

    username = (args.username or '').strip()
    email = (args.email or '').strip().lower()
    password = args.password

    if not username:
        username = input('Username: ').strip()
    if not email:
        email = input('E-mail: ').strip().lower()
    if not password:
        while True:
            p1 = getpass('Senha: ')
            p2 = getpass('Confirme a senha: ')
            if p1 != p2:
                print('As senhas não conferem. Tente novamente.')
            elif not p1:
                print('A senha não pode ser vazia.')
            else:
                password = p1
                break

    ensure_tables()
    with SessionLocal() as sess:
        dup = user_exists(sess, username=username, email=email)
        if dup == 'username':
            print(f"Erro: já existe usuário com username '{username}'.")
            return
        if dup == 'email':
            print(f"Erro: já existe usuário com e-mail '{email}'.")
            return

        try:
            u = create_user(sess, username=username, email=email, password=password)
        except IntegrityError:
            sess.rollback()
            print("Erro de integridade (username/e-mail duplicado).")
            return

        print(f"Usuário criado: id={u.id}, username='{u.username}', email='{u.email}'")

if __name__ == '__main__':
    main()
