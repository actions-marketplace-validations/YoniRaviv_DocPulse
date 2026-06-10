class AuthService:
    def login(self, user: str, password: str) -> str:
        """Authenticate a user and return a session_token."""
        session_token = f"token-{user}"
        return session_token

    def logout(self, session_token: str) -> None:
        """Invalidate the given session_token."""
        pass
