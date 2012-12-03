# -*- coding: utf-8 -*-

import struct
from binascii import hexlify, unhexlify
import datetime
try:
    import ujson as json
except ImportError:
    import simplejson as json

from gevent import select, ssl, socket

from django.db import models
from django.conf import settings
from django.utils import timezone

from backends.pool import SocketConnectionPool


class NotificationPayloadSizeExceeded(Exception):
    def __init__(
            self,
            message='The notification maximum payload size of 256 bytes was exceeded'):
        super(NotificationPayloadSizeExceeded, self).__init__(message)


class NotConnectedException(Exception):
    def __init__(
            self,
            message='You must open a socket connection before writing a message'):
        super(NotConnectedException, self).__init__(message)


class InvalidPassPhrase(Exception):
    def __init__(
            self,
            message='The passphrase for the private key appears to be invalid'):
        super(InvalidPassPhrase, self).__init__(message)


class BaseService(models.Model):
    """
    A base service class intended to be subclassed.
    """
    name = models.CharField(max_length=255)
    hostname = models.CharField(max_length=255)
    PORT = 0  # Should be overriden by subclass
    connection = None
    pool = None

    def connect(self, certfile):
        """
        Establishes an encrypted SSL socket connection to the service.
        After connecting the socket can be written to or read from.
        """
        # ssl in Python < 3.2 does not support certificates/keys as strings.
        # See http://bugs.python.org/issue3823
        try:
            if self.pool is None:
                self.pool = SocketConnectionPool(
                    hostname=self.hostname,
                    port=self.PORT,
                    ssl=True,
                    ssl_certfile=certfile)
            self.connection = self.pool.get_socket()
            return True
        except Exception as e:
            if getattr(settings, 'DEBUG', False):
                print e, e.__class__
            self.connection = None
        return False

    def disconnect(self):
        """
        Closes the SSL socket connection.
        """
        if self.connection is not None:
            try:
                # this fails is other side has already closed
                self.connection.shutdown(socket.SHUT_WR)
            except:
                pass
            self.connection.close()
            self.connection = None

    class Meta:
        abstract = True


class APNService(BaseService):
    """
    Represents an Apple Notification Service either for live
    or sandbox notifications.
    """
    PORT = 2195
    fmt = '!cH32sH%ds'

    def connect(self):
        """
        Establishes an encrypted SSL socket connection to the service.
        After connecting the socket can be written to or read from.
        """
        return super(APNService, self).connect(
            certfile=settings.IOS_CERT)

    def push_notification_to_devices(self, notification, devices=None):
        """
        Sends the specific notification to devices.
        if `devices` is not supplied, all devices in the `APNService`'s device
        list will be sent the notification.
        """
        if devices is None:
            devices = self.device_set.filter(is_active=True)
        if self.connect():
            try:
                self._write_message(notification, devices)
            except Exception as e:
                if getattr(settings, 'DEBUG', False):
                    print e, e.__class__

    def _write_message(self, notification, devices):
        """
        Writes the message for the supplied devices to
        the APN Service SSL socket.
        """
        if not isinstance(notification, Notification):
            raise TypeError('notification should be an instance of '
                            'ios_notifications.models.Notification')
        with self.connection as connection:
            # each device is notify individually
            for device in devices:
                kwargs = {}
                if hasattr(device, 'badge'):
                    kwargs['badge'] = device.badge
                payload = self.get_payload(notification, **kwargs)
                connection.send(self.pack_message(payload, device))
            if isinstance(devices, models.query.QuerySet):
                devices.update(last_notified_at=datetime.datetime.now())
            else:
                for device in devices:
                    device.last_notified_at = datetime.datetime.now()
                    device.save()
            notification.last_sent_at = datetime.datetime.now()
            notification.save()

    def get_payload(self, notification, **kwargs):
        aps = {'alert': notification.message}
        if 'badge' in kwargs:
            aps['badge'] = kwargs['badge']
        elif notification.badge is not None:
            aps['badge'] = notification.badge
        if notification.sound is not None:
            aps['sound'] = notification.sound

        message = {'aps': aps}
        payload = json.dumps(message)

        if len(payload) > 256:
            raise NotificationPayloadSizeExceeded

        return payload

    def pack_message(self, payload, device):
        """
        Converts a notification payload into binary form.
        """
        if len(payload) > 256:
            raise NotificationPayloadSizeExceeded
        if not isinstance(device, Device):
            raise TypeError('device must be an instance of '
                            'ios_notifications.models.Device')

        msg = struct.pack(
            self.fmt % len(payload),
            chr(0),
            32,
            unhexlify(device.token),
            len(payload),
            payload)
        return msg

    def __unicode__(self):
        return u'APNService %s' % self.name

    class Meta:
        unique_together = ('name', 'hostname')


class Notification(models.Model):
    """
    Represents a notification which can be pushed to an iOS device.
    """
    message = models.CharField(max_length=200)
    badge = models.PositiveIntegerField(default=1, null=True)
    sound = models.CharField(max_length=30, null=True, default='default')

    created_at = models.DateTimeField(
        auto_now_add=True,
        default=timezone.now)
    last_sent_at = models.DateTimeField(
        null=True,
        blank=True)

    # def push_to_all_devices(self):
    #     """
    #     Pushes this notification to all active devices using the
    #     notification's related APN service.
    #     """
    #     self.service.push_notification_to_devices(self)

    def __unicode__(self):
        return u'Notification: %s' % self.message

    @staticmethod
    def is_valid_length(message, badge=None, sound=None):
        """
        Determines if a notification payload is a valid length.

        returns bool
        """
        aps = {'alert': message}
        if badge is not None:
            aps['badge'] = badge
        if sound is not None:
            aps['sound'] = sound
        message = {'aps': aps}
        payload = json.dumps(message)
        return len(payload) <= 256


class Device(models.Model):
    """
    Represents an iOS device with unique token.
    """
    token = models.CharField(max_length=64, blank=False, null=False)
    is_active = models.BooleanField(default=True)
    service = models.ForeignKey(APNService)
    user = models.ForeignKey(
        'auth.User',
        null=True,
        related_name='devices')
    users = models.ManyToManyField(
        'auth.User',
        null=True,
        blank=True,
        related_name='ios_devices')
    platform = models.CharField(max_length=30, blank=True, null=True)
    display = models.CharField(max_length=30, blank=True, null=True)
    os_version = models.CharField(max_length=20, blank=True, null=True)

    deactivated_at = models.DateTimeField(
        null=True,
        blank=True)
    added_at = models.DateTimeField(
        auto_now_add=True,
        default=timezone.now)
    last_notified_at = models.DateTimeField(
        null=True,
        blank=True)

    def push_notification(self, notification):
        """
        Pushes a ios_notifications.models.Notification instance to
        the device. For more details see
        http://developer.apple.com/library/mac/#documentation/NetworkingInternet/Conceptual/RemoteNotificationsPG/ApplePushService/ApplePushService.html
        """
        if not isinstance(notification, Notification):
            raise TypeError('notification should be an instance of'
                            'ios_notifications.models.Notification')

        notification.service.push_notification_to_devices(notification, [self])
        self.save()

    def __unicode__(self):
        return u'Device %s' % self.token

    class Meta:
        unique_together = ('token', 'service')


class FeedbackService(BaseService):
    """
    The service provided by Apple to inform you of devices which no longer
    have your app installed and to which notifications have failed a number
    of times. Use this class to check the feedback service and deactivate
    any devices it informs you about.

    https://developer.apple.com/library/ios/#documentation/NetworkingInternet/Conceptual/RemoteNotificationsPG/CommunicatingWIthAPS/CommunicatingWIthAPS.html#//apple_ref/doc/uid/TP40008194-CH101-SW3
    """
    apn_service = models.ForeignKey(APNService)
    PORT = 2196
    fmt = '!lh32s'

    def connect(self):
        """
        Establishes an encrypted socket connection to the feedback service.
        """
        return super(FeedbackService, self).connect(certfile=settings.IOS_CERT)

    def call(self):
        """
        Calls the feedback service and deactivates any devices
        the feedback service mentions.
        """
        if self.connect():
            device_tokens = []
            while True:
            # 38 being the length in bytes of the binary format feedback tuple.
                data = self.connection.recv(38)
                if not data:
                    break
                timestamp, token_length, token = struct.unpack(self.fmt, data)
                device_token = hexlify(token)
                device_tokens.append(device_token)
            devices = Device.objects.filter(
                token__in=device_tokens, service=self.apn_service)
            devices.update(
                is_active=False, deactivated_at=datetime.datetime.now())
            self.disconnect()
            return devices.count()

    def __unicode__(self):
        return u'FeedbackService %s' % self.name

    class Meta:
        unique_together = ('name', 'hostname')
