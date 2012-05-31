import sys
from time import time

from pulsar import CommandNotFound
from pulsar.utils.log import LocalMixin

from .defer import Deferred, is_async, make_async, iteritems
from .mailbox import mailbox, ActorMessage
from .access import get_actor 
from . import commands

__all__ = ['ActorMessage',
           'ActorProxyDeferred',
           'ActorProxy',
           'ActorProxyMonitor',
           'ActorLink',
           'get_proxy']

def get_proxy(obj, safe = False):
    if isinstance(obj,ActorProxy):
        return obj
    elif hasattr(obj,'proxy'):
        return get_proxy(obj.proxy)
    else:
        if safe:
            return None
        else:
            raise ValueError('"{0}" is not an actor or actor proxy.'\
                             .format(obj))
            
            
class ActorProxyDeferred(Deferred):
    '''A :class:`Deferred` for an :class:`ActorProxy`. This instance will be
obtain and :class:`ActorProxy` result once the remote :class:`Actor` is fully
functional.

.. attribute:: aid

    The the remote :attr:`Actor` id
     
'''
    def __init__(self, aid, msg=None):
        super(ActorProxyDeferred,self).__init__()
        if msg is None:
            # In this case aid is an instance of an ActorProxyMonitor
            proxy = aid
            self.aid = proxy.aid
            proxy.on_address = self
        else:
            self.aid = aid
            # simply listent for the calbacks and errorbacks
            msg.addBoth(self.callback)
    
    def __str__(self):
        return '{0}({1})'.format(self.__class__,self.aid)
    __repr__ = __str__
    
    
class ActorProxy(LocalMixin):
    '''This is an important component in pulsar concurrent framework. An
instance of this class behaves as a proxy for a remote `underlying` 
:class:`Actor` instance.
This is a lightweight class which delegates function calls to the underlying
remote object.

It is pickable and therefore can be send from actor to actor using pulsar
messaging.

A proxy exposes all the underlying remote functions which have been implemented
in the actor class by prefixing with ``actor_``
(see the :class:`pulsar.ActorMetaClass` documentation).

By default each actor comes with a set of remote functions:

 * ``info`` returns a dictionary of information about the actor
 * ``ping`` returns ``pong``.
 * ``notify``
 * ``stop`` stop the actor
 * ``on_actor_exit``
 * ``callback``

For example, lets say we have a proxy ``a`` and an actor (or proxy) ``b``::

    a.send(b,'notify','hello there!')
    
will send a message to actor ``a`` from sender ``b`` invoking
action ``notify`` with parameter ``"hello there!"``.
    

.. attribute:: proxyid

    Unique ID for the remote object
    
.. attribute:: remotes

    dictionary of remote functions names with value indicating if the
    remote function will acknowledge the call or not.
    
.. attribute:: timeout

    the value of the underlying :attr:`pulsar.Actor.timeout` attribute
'''     
    def __init__(self, impl):
        self.aid = impl.aid
        self.commands_set = impl.commands_set
        # impl can be an actor or an actor impl,
        # which does not have the address attribute
        self.address = getattr(impl, 'address', None)
        self.timeout = impl.timeout
        self.loglevel = impl.loglevel
            
    @property
    def mailbox(self):
        '''Actor mailbox'''
        if self.address:
            return get_actor().proxy_mailbox(self.address)
        
    def receive_from(self, sender, command, *args, **kwargs):
        '''Send an :class:`ActorMessage` to the underlying actor
(the receiver). This is the low level function call for
communicating between actors.

:parameter sender: :class:`Actor` sending the message.
:parameter command: the command of the message.
    Default ``None``.
:parameter args: non positional arguments of message body.
:parameter kwargs: key-valued arguments of message body.
:parameter ack: If ``True`` the receiving actor will send a callback.
    If the action is provided and available, this parameter will be overritten.
:rtype: an instance of :class:`ActorMessage`.

When sending a message, first we check the ``sender`` outbox. If that is
not available, we get the receiver ``inbox`` and hope it can carry the message.
If there is no inbox either, abort the message passing and log a critical error.
'''
        mailbox = self.mailbox
        if sender is None:
            sender = get_actor()
        if not mailbox:
            sender.log.critical('Cannot send a message to {0}. No\
 mailbox available.'.format(self))
            return
        cmd = commands.get(command, self.commands_set)
        if not cmd:
            raise CommandNotFound(command)
        msg = ActorMessage(cmd.__name__, sender, self.aid, args, kwargs)
        if cmd.ack:
            return mailbox.execute(msg)
        else:
            return mailbox.send(msg)
        
    def __repr__(self):
        return self.aid
    __str__ = __repr__
    
    def __eq__(self, o):
        o = get_proxy(o,True)
        return o and self.aid == o.aid
    
    def __ne__(self, o):
        return not self.__eq__(o)

    def local_info(self):
        '''Return a dictionary containing information about the remote
object including, aid (actor id), timeout and mailbox size.'''
        return {'aid':self.aid[:8],
                'timeout':self.timeout,
                'mailbox_size':self.mailbox.qsize()}
        
    def stop(self, sender=None):
        '''Stop the remote :class:`Actor`'''
        self.receive_from(sender, 'stop')
        

class ActorProxyMonitor(ActorProxy):
    '''A specialised :class:`ActorProxy` class which contains additional
information about the remote underlying :class:`pulsar.Actor`. Unlike the
:class:`pulsar.ActorProxy` class, instances of this class are not pickable and
therefore remain in the :class:`Arbiter` process domain, which is the
process where they have been created.

.. attribute:: impl

    The :class:`Concurrency` instance for the remote :class:`Actor`.
    
.. attribute:: info

    Dictionary of information regarding the remote :class:`Actor`
'''
    monitor = None
    def __init__(self, impl):
        self.impl = impl
        self.info = {'last_notified':time()}
        self.stopping_loops = 0
        super(ActorProxyMonitor,self).__init__(impl)
        
    @property
    def notified(self):
        return self.info['last_notified']
    
    @property
    def pid(self):
        return self.impl.pid
    
    @property
    def proxy(self):
        return ActorProxy(self)
    
    def is_alive(self):
        '''True if underlying actor is alive'''
        return self.impl.is_alive()
        
    def terminate(self):
        '''Terminate life of underlying actor.'''
        self.impl.terminate()
    
    def join(self, timeout=None):
        '''Wait until the underlying actor terminates. If *timeout* is
provided, it raises an exception if the timeout is reached.'''
        self.impl.join(timeout=timeout)

    def start(self):
        '''Start the remote actor.'''
        self.impl.start()


class ActorLink(object):
    '''A callable utility for sending :class:`ActorMessage`
to linked :class:`Actor` instances.
.. attribute:: name

The :attr:`Actor.name` of the actor which will receive messages via
the :class:`ActorLink` from other actors.
An example on how to use an :class:`ActorLink` can be found in the
:class:`pulsar.apps.tasks.TaskQueueRpcMixin`, where the
``task_queue_manager`` attribute is a lint to the
:class:`pulsar.apps.tasks.TaskQueue`.
'''
    def __init__(self, name):
        self.name = name
        
    def proxy(self, sender):
        '''Get the :class:`ActorProxy` for the sender.'''
        proxy = sender.get_actor(self.name)
        if not proxy:
            raise ValueError('Got a request from actor "{0}" which is\
not linked with "{1}".'.format(sender,self.name))
        return proxy
    
    def get_callback(self, sender, action, *args, **kwargs):
        '''Create an :class:`ActorLinkCallback` for sending messages
with additional parameters.

:parameter sender: The :class:`Actor` sending the message.
:parameter action: The *action* in the :class:`ActorMessage`.
:parameter args: same as :attr:`ActorMessage.args`
:parameter kwargs: same as :attr:`ActorMessage.kwargs`
:rtype: an :class:`ActorLinkCallback`.
'''
        if isinstance(sender,dict):
            # This is an environment dictionary
            local = sender
            sender = sender.get('pulsar.actor')
        else:
            local = kwargs.pop('local',None)
        proxy = self.proxy(sender)
        res = ActorLinkCallback(self, proxy, sender, action, args, kwargs)
        if local:
            res._local = local
        return res
        
    def __call__(self, sender, action, *args, **kwargs):
        return self.get_callback(sender, action, *args, **kwargs)()