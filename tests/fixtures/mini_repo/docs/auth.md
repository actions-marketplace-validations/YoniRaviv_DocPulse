# Authentication

This document describes the authentication system.

## Login

The `AuthService.login` method authenticates a user with their credentials.
It validates the user and returns a session_token upon success.

## Sessions

Each authenticated user receives a `session_token` that identifies their session.
The token is used for subsequent API requests and expires after a configurable duration.
