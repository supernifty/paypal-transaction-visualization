import base64
import cgi # 2.5
import decimal
import hmac
import hashlib
import logging
import re
import time
import urllib
import urllib2
import urlparse

from google.appengine.api import urlfetch

# hack to enable urllib to work with Python
import os
os.environ['foo_proxy'] = 'bar'

from django.utils import simplejson as json

import settings

class Pay( object ):
  def __init__( self, amount, return_url, cancel_url, remote_address, ipn_url=None, shipping=False ):
    headers = {
      'X-PAYPAL-SECURITY-USERID': settings.PAYPAL_USERID, 
      'X-PAYPAL-SECURITY-PASSWORD': settings.PAYPAL_PASSWORD, 
      'X-PAYPAL-SECURITY-SIGNATURE': settings.PAYPAL_SIGNATURE, 
      'X-PAYPAL-REQUEST-DATA-FORMAT': 'JSON',
      'X-PAYPAL-RESPONSE-DATA-FORMAT': 'JSON',
      'X-PAYPAL-APPLICATION-ID': settings.PAYPAL_APPLICATION_ID,
      'X-PAYPAL-DEVICE-IPADDRESS': remote_address,
    }

    data = {
      'currencyCode': 'USD',
      'returnUrl': return_url,
      'cancelUrl': cancel_url,
      'requestEnvelope': { 'errorLanguage': 'en_US' },
    } 

    if shipping:
      data['actionType'] = 'CREATE'
    else:
      data['actionType'] = 'PAY'

    data['receiverList'] = { 'receiver': [ { 'email': settings.PAYPAL_EMAIL, 'amount': '%f' % amount } ] }

    if ipn_url != None:
      data['ipnNotificationUrl'] = ipn_url

    self.raw_request = json.dumps(data)
    #request = urllib2.Request( "%s%s" % ( settings.PAYPAL_ENDPOINT, "Pay" ), data=self.raw_request, headers=headers )
    #self.raw_response = urllib2.urlopen( request ).read() 
    self.raw_response = url_request( "%s%s" % ( settings.PAYPAL_ENDPOINT, "Pay" ), data=self.raw_request, headers=headers ).content() 
    logging.debug( "response was: %s" % self.raw_response )
    self.response = json.loads( self.raw_response )

    if shipping:
      # generate setpaymentoptions request
      options_raw_request = json.dumps( { 
        'payKey': self.paykey(),
        'senderOptions': { 'requireShippingAddressSelection': 'true', 'shareAddress': 'true' },
        'requestEnvelope': { 'errorLanguage': 'en_US' }
      } )
      options_raw_response = url_request( "%s%s" % ( settings.PAYPAL_ENDPOINT, "SetPaymentOptions" ), data=options_raw_request, headers=headers ).content() 
      logging.debug( 'SetPaymentOptions response: %s' % options_raw_response )
      # TODO check response was OK
    
  def status( self ):
    if self.response.has_key( 'paymentExecStatus' ):
      return self.response['paymentExecStatus']
    else:
      return None 

  def amount( self ):
    return decimal.Decimal(self.results[ 'payment_gross' ])

  def paykey( self ):
    return self.response['payKey']

  def next_url( self ):
    return '%s?cmd=_ap-payment&paykey=%s' % ( settings.PAYPAL_PAYMENT_HOST, self.response['payKey'] )

class IPN( object ):
  def __init__( self, request ):
    # verify that the request is paypal's
    self.error = None
    #verify_request = urllib2.Request( "%s?cmd=_notify-validate" % settings.PAYPAL_PAYMENT_HOST, data=urllib.urlencode( request.POST.copy() ) )
    #verify_response = urllib2.urlopen( verify_request )
    verify_response = url_request( "%s?cmd=_notify-validate" % settings.PAYPAL_PAYMENT_HOST, data=urllib.urlencode( request.POST.copy() ) )
    # check code
    if verify_response.code() != 200:
      self.error = 'PayPal response code was %i' % verify_response.code()
      return
    # check response
    raw_response = verify_response.content()
    if raw_response != 'VERIFIED':
      self.error = 'PayPal response was "%s"' % raw_response
      return
    # check payment status
    if request.get('status') != 'COMPLETED':
      self.error = 'PayPal status was "%s"' % request.get('status')
      return

    (currency, amount) = request.get( "transaction[0].amount" ).split(' ')
    if currency != 'USD':
      self.error = 'Incorrect currency %s' % currency
      return

    self.amount = decimal.Decimal(amount)

  def success( self ):
    return self.error == None

class ShippingAddress( object ):
  def __init__( self, paykey, remote_address ):
    headers = {
      'X-PAYPAL-SECURITY-USERID': settings.PAYPAL_USERID, 
      'X-PAYPAL-SECURITY-PASSWORD': settings.PAYPAL_PASSWORD, 
      'X-PAYPAL-SECURITY-SIGNATURE': settings.PAYPAL_SIGNATURE, 
      'X-PAYPAL-REQUEST-DATA-FORMAT': 'JSON',
      'X-PAYPAL-RESPONSE-DATA-FORMAT': 'JSON',
      'X-PAYPAL-APPLICATION-ID': settings.PAYPAL_APPLICATION_ID,
      'X-PAYPAL-DEVICE-IPADDRESS': remote_address,
    }

    data = {
      'key': paykey,
      'requestEnvelope': { 'errorLanguage': 'en_US' },
    } 

    self.raw_request = json.dumps(data)
    self.raw_response = url_request( "%s%s" % ( settings.PAYPAL_ENDPOINT, "GetShippingAddresses" ), data=self.raw_request, headers=headers ).content() 
    logging.debug( "response was: %s" % self.raw_response )
    self.response = json.loads( self.raw_response )

class RequestPermissions( object ):
  def __init__( self, return_url, permissions, remote_address ):
    headers = {
      'X-PAYPAL-SECURITY-USERID': settings.PAYPAL_USERID, 
      'X-PAYPAL-SECURITY-PASSWORD': settings.PAYPAL_PASSWORD, 
      'X-PAYPAL-SECURITY-SIGNATURE': settings.PAYPAL_SIGNATURE, 
      'X-PAYPAL-REQUEST-DATA-FORMAT': 'JSON',
      'X-PAYPAL-RESPONSE-DATA-FORMAT': 'JSON',
      'X-PAYPAL-APPLICATION-ID': settings.PAYPAL_APPLICATION_ID,
      'X-PAYPAL-DEVICE-IPADDRESS': remote_address,
    }

    data = {
      'scope': permissions,
      'requestEnvelope': { 'errorLanguage': 'en_US' },
      'callback': return_url
    }

    self.raw_request = json.dumps(data)
    self.raw_response = url_request( "%s%s" % ( settings.PAYPAL_ENDPOINT, "RequestPermissions" ), data=self.raw_request, headers=headers ).content()
    logging.debug( "response was: %s" % self.raw_response )
    self.response = json.loads( self.raw_response )
    
  def ok( self ):
    return self.response.has_key( 'token' )

  def next_url( self ):
    return '%s?cmd=_grant-permission&request_token=%s' % ( settings.PAYPAL_PAYMENT_HOST, self.response['token'] )
    
class AccessPermissions( object ):
  def __init__( self, token, verifier, remote_address ):
    headers = {
      'X-PAYPAL-SECURITY-USERID': settings.PAYPAL_USERID, 
      'X-PAYPAL-SECURITY-PASSWORD': settings.PAYPAL_PASSWORD, 
      'X-PAYPAL-SECURITY-SIGNATURE': settings.PAYPAL_SIGNATURE, 
      'X-PAYPAL-REQUEST-DATA-FORMAT': 'JSON',
      'X-PAYPAL-RESPONSE-DATA-FORMAT': 'JSON',
      'X-PAYPAL-APPLICATION-ID': settings.PAYPAL_APPLICATION_ID,
      'X-PAYPAL-DEVICE-IPADDRESS': remote_address,
    }

    data = {
      'token': token,
      'verifier': verifier,
      'requestEnvelope': { 'errorLanguage': 'en_US' },
    }

    self.raw_request = json.dumps(data)
    self.raw_response = url_request( "%s%s" % ( settings.PAYPAL_ENDPOINT, "GetAccessToken" ), data=self.raw_request, headers=headers ).content()
    logging.debug( "response was: %s" % self.raw_response )
    self.response = json.loads( self.raw_response )
    
  def ok( self ):
    return self.response.has_key( 'token' )
    
  def token( self ):
    return self.response[ 'token' ]
    
  def token_secret( self ):
    return self.response[ 'tokenSecret' ]

class TransactionSearch( object ):
  def __init__( self, start_date, signature, remote_address ):
    headers = {
      'X-PP-AUTHORIZATION': signature,
    }

    data = {
      'METHOD': 'TransactionSearch',
      'VERSION': '74.0',
      'STARTDATE': start_date.isoformat(),
    }

    self.raw_request = urllib.urlencode( data )
    self.raw_response = url_request( "%s" % settings.PAYPAL_API_ENDPOINT, data=self.raw_request, headers=headers ).content()
    logging.debug( "response was: %s" % self.raw_response )
    self.response = cgi.parse_qs( self.raw_response ) # 2.5
    self.items = []
    self.count = 0
    while self.response.has_key( "L_TIMESTAMP%i" % self.count ):
      self.items.append( {
        'timestamp': self.safe_get( "L_TIMESTAMP%i" % self.count ),
        'timezone': self.safe_get( 'L_TIMEZONE%i' % self.count ),
        'type': self.safe_get( 'L_TYPE%i' % self.count ),
        'email': self.safe_get( 'L_EMAIL%i' % self.count ),
        'name': self.safe_get( 'L_NAME%i' % self.count ),
        'transaction_id': self.safe_get( 'L_TRANSACTIONID%i' % self.count ),
        'status': self.safe_get( 'L_STATUS%i' % self.count ),
        'amount': self.safe_get( 'L_AMT%i' % self.count ),
        'fee': self.safe_get( 'L_FEEAMT%i' % self.count ),
        'net_amount': self.safe_get( 'L_NETAMT%i' % self.count ),
      } )
      self.count += 1

  def ok( self ):
    return self.response.has_key( 'ACK' ) and self.response[ 'ACK' ][0] == 'Success'

  def safe_get( self, field ):
    if self.response.has_key( field ):
      return self.response[ field ][0]
    else:
      return ''

class AuthorizationSignature( object ):
  '''generates the X-PP-AUTHORIZATION header'''
  def __init__( self, token, token_secret, parameters ):
    self.token = token
    self.timestamp = int( time.time() )
    self.key = "%s&%s" % ( settings.PAYPAL_PASSWORD, AuthorizationSignature.encode( token_secret ) )
    self.base = "%s&%s" % ( 'POST', AuthorizationSignature.encode( settings.PAYPAL_API_ENDPOINT ) )
    self.params = "oauth_consumer_key=%s&oauth_signature_method=HMAC-SHA1&oauth_timestamp=%i&oauth_token=%s&oauth_version=1.0" % ( 
      settings.PAYPAL_USERID, self.timestamp, token )
    self.raw = "%s&%s" % ( self.base, AuthorizationSignature.encode( self.params ) )
    # sign
    self.hashed = hmac.new( self.key, self.raw, hashlib.sha1 )
    self.signed = base64.b64encode( self.hashed.digest() )
    logging.debug( "key: %s, params: %s, raw: %s, signed: %s, b64: %s" % ( self.key, self.params, self.raw, self.signed, self.signed ) )

  def signature( self ):
    return "timestamp=%i,token=%s,signature=%s" % ( self.timestamp, self.token, self.signed )

  @staticmethod
  def encode( s ):
    out = ''
    exp = re.compile( r'([A-Za-z0-9_]+)' )
    for c in s:
      if (re.match(exp, c)==None):
        out = out + "%"+hex(ord(c))[2:]
      elif (c==' '):
        out = out + "+"
      else:
        out = out + c
    return out
    
class url_request( object ): 
  '''wrapper for urlfetch'''
  def __init__( self, url, data=None, headers={} ):
    # urlfetch - validated
    self.response = urlfetch.fetch( url, payload=data, headers=headers, method=urlfetch.POST, validate_certificate=True )
    # urllib - not validated
    #request = urllib2.Request(url, data=data, headers=headers) 
    #self.response = urllib2.urlopen( https_request )

  def content( self ):
    return self.response.content 

  def code( self ):
    return self.response.status_code
