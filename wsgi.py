try:
    from app import app as application
except ImportError:
    from app import create_app
    application = create_app()
