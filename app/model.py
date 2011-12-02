from google.appengine.ext import db

class Session(db.Model):
  session = db.StringProperty()
  signature = db.TextProperty()
