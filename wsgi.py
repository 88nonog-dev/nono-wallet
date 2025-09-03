# نصدّر متغير اسمه app لأن startCommand يستخدم wsgi:app
try:
    from app import application as app
except ImportError:
    # احتياط إذا عندك متغير app داخل app.py
    from app import app as app

# نُبقي application أيضًا متاح (اختياري)
application = app
