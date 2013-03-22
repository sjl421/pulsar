'''The example is a :ref:`WSGI application <apps-wsgi>`
with a :ref:`websocket middleware <apps-ws>` which connects to an
IMAP4 server to retrieve and send emails.

The connection with the IMAP4 server is obtained using the IMAP4 API in
twisted 12.3 or later. The example uses
:ref:`pulsar-twisted integration <tutorials-twisted>` module.

To run the server you need to create a :mod:`config.py` file in the
the :mod:`examples.webmail` directory containing::

    # the adress of your mail server
    incoming_mail='ssl:host=imap.gmail.com:port=993'
    # username & password
    username=
    password=

And type::

    python manage.py
    
Open a web browser at http://localhost:8060 and you should see the web app.

For information on twised IMAP4 client library check this example:

http://twistedmatrix.com/documents/current/mail/examples/imap4client.py

Implementation
==================

.. autoclass:: WsMail
   :members:
   :member-order: bysource
   
'''
import os
import sys
import json
from functools import partial
import time
try:
    import pulsar
except ImportError: #pragma nocover
    sys.path.append('../../')
    import pulsar
from pulsar.utils.pep import zip
from pulsar.apps import ws, wsgi
try:
    from pulsar.lib.tx import twisted
    from twisted.internet import protocol, defer, endpoints, reactor
    from twisted.mail import imap4
except ImportError: #pragma    nocover
    twisted = None    # This is for when we build docs

try:
    import config
except ImportError:
    config = None

ASSET_DIR = os.path.join(os.path.dirname(__file__), 'assets')

    
def mail_client(timeout=10):
    '''Create a new mail client using twisted IMAP4 library.'''
    endpoint = endpoints.clientFromString(reactor, config.incoming_mail)
    endpoint._timeout = timeout
    factory = protocol.Factory()
    factory.protocol = imap4.IMAP4Client
    client = yield endpoint.connect(factory)
    yield client.login(config.username, config.password)
    yield client.select('INBOX')
    yield client
    #info = yield client.fetchEnvelope(imap4.MessageSet(1))
    #print 'First message subject:', info[1]['ENVELOPE'][1]


class WsMail(ws.WS):
    ''':ref:`Websocket handler <websocket-handler>` for fetching and
sending mail via the twisted IMAP4 library.'''
    def on_open(self, request):
        '''When the websocket starts, it create a new mail client.'''
        client = yield mail_client()
        #add the mail client to the environ cache
        request.cache['mailclient'] = client
        # retrieve the list of mailboxes
        yield self._send_mailboxes(request)
        
    def on_message(self, request, msg):
        client = request.cache.get('mailclient')
        if msg and client:
            msg = json.loads(msg)
            if 'mailbox' in msg:
                mailbox = msg[mailbox]
                future = client.examine(mailbox)
                yield future
                result = future.result
                self.write(request, json.dumps({'mailbox': result}))

    def _send_mailboxes(self, request):
        client = request.cache['mailclient']
        result = yield client.list("","*")
        result = sorted([e[2] for e in result])
        self.write(request, json.dumps({'list': result}))


class Web(wsgi.Router):
    '''Main web page'''    
    def get(self, request):
        data = open(os.path.join(ASSET_DIR, 'mail.html')).read()
        request.response.content = data % request.environ
        request.response.content_type = 'text/html'
        return request.response.start()


class WebMail(wsgi.LazyWsgi):

    def setup(self):
        return wsgi.WsgiHandler([ws.WebSocket('/message', WsMail()),
                                 wsgi.MediaRouter('/media', ASSET_DIR),
                                 Web('/')])
    
    
def server(**kwargs):
    return wsgi.WSGIServer(name='webmail', callable=WebMail(), **kwargs)


if __name__ == '__main__':  #pragma nocover
    server().start()