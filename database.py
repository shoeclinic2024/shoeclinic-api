from flask_sqlalchemy import SQLAlchemy

# Create SQLAlchemy instance without binding to app
# This avoids circular imports
# Use model_class to prevent automatic model registration issues
db = SQLAlchemy()


