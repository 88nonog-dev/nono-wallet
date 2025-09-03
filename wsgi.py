# نُصدر app لأن railway.toml يستخدم startCommand = "gunicorn wsgi:app ..."
try:
    from app import application as app
except ImportError:
    from app import app as app

# إبقاء alias application (اختياري)
application = app
