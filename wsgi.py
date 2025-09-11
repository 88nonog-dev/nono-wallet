<<<<<<< HEAD
from app import app, db
=======
﻿from app import app, db
>>>>>>> 044c657 (fix(wsgi): correct indentation and UTF-8 encoding)

with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        app.logger.warning(f"db.create_all warning: {e}")
