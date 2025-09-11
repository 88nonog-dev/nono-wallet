<<<<<<< HEAD
ffrom app import app, db

if __name__ == "__main__":
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            app.logger.warning(f"db.create_all warning: {e}")
=======
﻿from app import app
>>>>>>> ea4d328 (fix: final clean wsgi file)
