from app.api import Settings, create_app

app = create_app(Settings.from_env("user"))
