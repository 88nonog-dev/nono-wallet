from app import app, db


# تأكد من إنشاء الجداول عند بدء التشغيل (للبيئات البسيطة بدون Alembic)
with app.app_context():
try:
db.create_all()
except Exception as e:
app.logger.warning(f"db.create_all warning: {e}")
