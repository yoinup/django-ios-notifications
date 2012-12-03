# coding=utf-8

import contextlib

from gevent.queue import Queue
from gevent import ssl, socket


class SocketConnectionPool(object):
    def __init__(
            self, hostname, port,
            options={'family': socket.AF_INET, 'type': socket.SOCK_STREAM},
            ssl=False, ssl_version=ssl.PROTOCOL_SSLv3,
            ssl_certfile=None, max=1):
        self.max = max
        self.size = 0
        self.hostname = hostname
        self.port = port
        self.options = options
        if ssl:
            self.ssl_version = ssl_version
            self.ssl_certfile = ssl_certfile
        self.pool = Queue()

    @contextlib.contextmanager
    def get_socket(self):
        """
            using contextmanager decorator this function is defined as a
            factory and can be use with a 'with' statement

            exceptions raised inside with-statement are handled here and
            finally block is always called after with-statement finish.
        """
        _sock = self._connect_socket()
        try:
            yield _sock
        except:
            _sock.close()
            _sock = None
            raise
        finally:
            if _sock is not None:
                self.free_socket(_sock)

    def free_socket(self, sock):
        """
            put the socket back in the queue
        """
        self.pool.put(sock)

    def _open_socket(self):
        """
            Open socket with family and proto versions,
            and wrap it as SSL socket
        """
        _sock = socket.socket(**self.options)
        return ssl.wrap_socket(
            _sock,
            certfile=self.ssl_certfile,
            ssl_version=self.ssl_version)

    def _connect_socket(self):
        """
            Return available socket from queue or create new one.
            If queue has max size, queue's get() will block until any
            sockets is free
        """
        if self.size >= self.max or self.pool.qsize():
            return self.pool.get()
        else:
            try:
                _sock = self._open_socket()
                _sock.connect(
                    tuple([self.hostname, self.port]))
                self.size += 1
                return _sock
            except IOError:
                raise IOError("Cannot create socket for %s:%s" % (
                    self.hostname, self.port))
