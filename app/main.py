import cgi
import datetime
import decimal
import logging
import os
import random
import simplejson
import urllib

from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import login_required
from google.appengine.ext.webapp.util import run_wsgi_app

# import model
import paypal
import settings

# hack to enable urllib to work with Python 2.6
import os
os.environ['foo_proxy'] = 'bar'
import urllib
urllib.getproxies_macosx_sysconf = lambda: {}

class Home(webapp.RequestHandler):
  def get(self):
    data = {}
    path = os.path.join(os.path.dirname(__file__), 'templates/main.htm')
    self.response.out.write(template.render(path, data))

  def post(self):
    # start and redirect to paypal
    permission = paypal.RequestPermissions( "%sreturn" % self.request.uri, "TRANSACTION_SEARCH", self.request.remote_addr )
    if permission.ok():
      logging.debug( "next_url: " + permission.next_url() )
      self.redirect( permission.next_url() )
    else:
      data = { 'message': 'Request Permission failed' }
      path = os.path.join(os.path.dirname(__file__), 'templates/main.htm')
      self.response.out.write(template.render(path, data))
    
class Return(webapp.RequestHandler):
  def get(self):
    access = paypal.AccessPermissions( self.request.get( "request_token" ), self.request.get( "verification_code" ), self.request.remote_addr )
    if access.ok():
      signature = paypal.AuthorizationSignature( access.token(), access.token_secret(), self.request.remote_addr )
      start_date = datetime.datetime.now() - datetime.timedelta( days=365 )
      tx = paypal.TransactionSearch( start_date, signature.signature(), self.request.remote_addr )
      if tx.ok():
        # build monthly array
        month = start_date.month
        year = start_date.year
        months = {}
        for m in xrange( 0, 12 ):
          months[ "M%04i/%02i" % ( year, month ) ] = { 'month': month, 'year': year, 'in': 0.00, 'out': 0.00, 'net': 0.00 }
          month += 1
          if month == 13:
            month = 1
            year += 1

        for i in tx.items:
          date = i['timestamp'].split( 'T' )[0]
          d = datetime.datetime.strptime( date, "%Y-%m-%d")
          key = "M%04i/%02i" % ( d.year, d.month )
          if months.has_key( key ):
            amount = float( i[ 'net_amount' ] )
            if amount > 0:
              months[ key ][ 'in' ] += amount
            else:
              months[ key ][ 'out' ] += amount
            months[ key ][ 'net' ] += amount
          else:
            logging.debug( "key " + key + " not found" )
        
        month_list = []
        in_list = []
        out_list = []
        net_list = []
        keys = months.keys()
        keys.sort()
        maximum = 0
        minimum = 0
        for k in keys:
          month_list.append( "%02i/%04i" % ( months[k]['month'], months[k]['year'] ) )
          in_list.append( months[k]['in'] )
          out_list.append( months[k]['out'] )
          net_list.append( months[k]['net'] )
          if months[k]['in'] > maximum:
            maximum = months[k]['in']
          if months[k]['out'] < minimum:
            minimum = months[k]['out']
        data = { 'result': tx.items, 'months': month_list, 'max': maximum, 'min': minimum, 'in_list': in_list, 'out_list': out_list, 'net_list': net_list }
        path = os.path.join(os.path.dirname(__file__), 'templates/tx.htm')
        self.response.out.write(template.render(path, data))
      else:
        data = { 'message': 'Transaction search failed' }
        path = os.path.join(os.path.dirname(__file__), 'templates/main.htm')
        self.response.out.write(template.render(path, data))
    else:
      data = { 'message': 'Get Access Token failed' }
      path = os.path.join(os.path.dirname(__file__), 'templates/main.htm')
      self.response.out.write(template.render(path, data))

application = webapp.WSGIApplication( [
    ('/', Home),
    ('/return', Return),
  ],
  debug=True)

def main():
  logging.getLogger().setLevel(logging.DEBUG)
  run_wsgi_app(application)

if __name__ == "__main__":
  main()

