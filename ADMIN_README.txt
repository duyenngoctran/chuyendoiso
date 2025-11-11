Admin login files added.

How to enable admin routes:
1) In your main app (app.py), make sure you have these imports at top:
   from flask import session
   from admin import admin_bp

2) Register blueprint and set secret key before running app:
   app.secret_key = 'change_this_to_a_random_secret'
   app.register_blueprint(admin_bp)

3) Default admin credential is admin / 123456 (change in admin.py).

Notes:
- This is a minimal admin login intended for local/dev usage only.
- For production use, integrate a proper user system and hash passwords.
