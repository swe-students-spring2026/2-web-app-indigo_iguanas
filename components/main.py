from flask import Flask
from flask_login import LoginManager
from components.dashboard import dashboard_bp

app = Flask(__name__)
app.secret_key = "supersecretkey"

# Register Blueprint
app.register_blueprint(dashboard_bp)

if __name__ == "__main__":
    app.run(debug=True)