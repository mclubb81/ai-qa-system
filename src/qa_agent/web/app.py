import secrets

from flask import Flask


def create_app() -> Flask:
    app = Flask(__name__)
    # Process-local random secret purely so flash() works -- not a security
    # boundary (this is a loopback-only, single-operator local tool).
    app.secret_key = secrets.token_hex(16)

    from qa_agent.web.routes import bp

    app.register_blueprint(bp)
    return app
