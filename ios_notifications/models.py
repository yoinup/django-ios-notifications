# -*- coding: utf-8 -*-

import struct
from binascii import hexlify, unhexlify
import logging
logger = logging.getLogger('djangoapp')

from gcm import GCM
from gcm.gcm import (
    GCMConnectionException, GCMUnavailableException,
    GCMMissingRegistrationException)

try:
    import ujson as json
except ImportError:
    import simplejson as json

from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile

from backends.pool import SocketConnectionPool
from utils import is_sequence
from yoin.utils import reduce_image
from yoin.fields import CharNullField


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

    class Meta:
        abstract = True


class APNService(object):
    """
    Represents an Apple Notification Service either for live
    or sandbox notifications.
    """
    hostname = settings.IOS_SERVICE_HOSTNAME
    PORT = 2195
    fmt = '!cH32sH%ds'

    def __init__(self, *args, **kwargs):
        self.connection = kwargs.get('connection', None)
        self.pool = kwargs.get('pool', None)
        self.certfile = kwargs.get('certfile', settings.IOS_CERT)

    def connect(self):
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
                    ssl_certfile=self.certfile,
                    max=7)
            return True
        except Exception as e:
            if getattr(settings, 'DEBUG', False):
                logger.error(
                    "[IOS] ERROR %(c)s: %(e)s",
                    {
                        'e': e,
                        'c': e.__class__
                    })
            raise
        return False

    def disconnect(self):
        """
        Closes the SSL socket connection.
        """
        if self.connection:
            with self.connection as connection:
                try:
                    self.pool.free_socket(connection)
                except:
                    pass

    def push_notification_to_devices(self, notification, devices=None):
        """
        Sends the specific notification to devices.
        if `devices` is not supplied, all devices in the `APNService`'s device
        list will be sent the notification.
        """
        if devices is None:
            devices = self.device_set.filter(
                is_active=True).values_list('token', flat=True)
        if not is_sequence(devices):
            devices = [devices]
        if self.connect():
            try:
                self._write_message(notification, devices)
                logger.info(
                    '[IOS] PUSH NOTIFICATION %(n)s SENT: %(d)s',
                    {
                        'n': notification.pk,
                        'd': ', '.join([str(i) for i in devices])
                    })
                return True
            except Exception as e:
                if not settings.DEBUG:
                    logger.error(
                        '[IOS] PUSH NOTIFICATION %(n)s FAILED: %(d)s -> %(e)s',
                        {
                            'n': notification.pk,
                            'd': ''.join([str(i) for i in devices]),
                            'e': e})
                raise
            return False

    def _write_message(self, notification, devices):
        """
        Writes the message for the supplied devices to
        the APN Service SSL socket.
        """
        if not isinstance(notification, Notification):
            raise TypeError('notification should be an instance of '
                            'ios_notifications.models.Notification')
        with self.pool.get_socket() as connection:
            # each device is notify individually
            for device in devices:
                kwargs = {}
                if hasattr(notification, '_badge'):
                    kwargs['badge'] = notification._badge
                payload = self.get_payload(notification, **kwargs)
                connection.send(self.pack_message(payload, device))

            Device.objects.filter(
                token__in=devices).update(last_notified_at=timezone.now())
            notification.last_sent_at = timezone.now()
            notification.save()

    def get_payload(self, notification, **kwargs):
        if hasattr(notification, '_message'):
            aps = {'alert': notification._message}
        else:
            aps = {'alert': notification.message}
        if 'badge' in kwargs:
            aps['badge'] = kwargs['badge']
        elif notification.badge is not None:
            aps['badge'] = notification.badge
        if notification.sound is not None:
            aps['sound'] = notification.sound
        if hasattr(notification, 'pk'):
            aps['kind'] = notification.pk
        if hasattr(notification, '_uri'):
            aps['notification'] = notification._uri

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
        if hasattr(device, 'token'):
            device = device.token
        msg = struct.pack(
            self.fmt % len(payload),
            chr(0),
            32,
            unhexlify(device),
            len(payload),
            payload)
        return msg

    def __unicode__(self):
        return u'APNService %s' % self.name

    class Meta:
        unique_together = ('name', 'hostname')


class GCMService(object):
    gcm = GCM(settings.GCM_API_KEY)

    def push_notification_to_devices(self, notification, devices=None):
        """
        Sends the specific notification to devices.
        if `devices` is not supplied, all devices in the `APNService`'s device
        list will be sent the notification.
        """
        if devices is None:
            devices = AndroidDevice.objects.filter(
                is_active=True).values_list('token', flat=True)
        if not is_sequence(devices):
            devices = [devices]
        try:
            self._write_message(notification, devices)
            logger.info(
                '[GCM] PUSH NOTIFICATION %(n)s SENT: %(d)s',
                {
                    'n': notification.pk,
                    'd': ''.join([str(i) for i in devices])
                })
            return True
        except GCMMissingRegistrationException:
            return True
        except Exception as e:
            if getattr(settings, 'DEBUG', False):
                logger.error(
                    '[GCM] PUSH NOTIFICATION %(n)s FAILED: %(d)s -> %(e)s',
                    {
                        'n': notification.pk,
                        'd': ''.join([str(i) for i in devices]),
                        'e': e})
        return False

    def _write_message(self, notification, devices):
        if not isinstance(notification, Notification):
            raise TypeError('notification should be an instance of '
                            'ios_notifications.models.Notification')
        kwargs = {}
        payload = self.get_payload(notification, **kwargs)
        response = self.gcm.json_request([d for d in devices], data=payload)
        if 'errors' in response:
            logger.info(response['errors'])
            # for error, reg_ids in response['errors'].items():
            #     # Check for errors and act accordingly
            #     if error is 'NotRegistered':
            #     # Remove reg_ids from database
            #         AndroidDevice.objects.filter(
            #             token=reg_ids).update(is_active=False)
        if 'canonical' in response:
            logger.info(response['canonical'])
            AndroidDevice.objects.filter(
                token__in=response['canonical'].keys()).delete()
        AndroidDevice.objects.filter(token__in=devices).update(
            last_notified_at=timezone.now())
        notification.last_sent_at = timezone.now()
        notification.save()

    def get_payload(self, notification, **kwargs):
        payload = {}
        if hasattr(notification, '_message'):
            payload['alert'] = notification._message
        else:
            payload['alert'] = notification.message
        if hasattr(notification, '_badge'):
            payload['badge'] = notification._badge
        if hasattr(notification, '_uri'):
            payload['notification'] = notification._uri
        if hasattr(notification, 'pk'):
            payload['kind'] = notification.pk

        return payload


class Notification(models.Model):
    """
    Represents a notification which can be pushed to an iOS device.
    """
    message = models.CharField(max_length=200)
    badge = models.PositiveIntegerField(default=1, null=True)
    sound = models.CharField(max_length=30, null=True, default='default')
    picture = models.ImageField(
        _(u'Rectangular picture'), upload_to='notifications/pictures',
        blank=True)
    picture_mobile = models.ImageField(
        _(u'Mobile picture'), upload_to='notifications/pictures/mob',
        blank=True)
    square_picture = models.ImageField(
        _(u'Square picture'), upload_to='notifications/square', blank=True)
    square_picture_mobile = models.ImageField(
        _(u'Mobile square picture'), upload_to='notifications/square/mob',
        blank=True)

    created_at = models.DateTimeField(
        auto_now_add=True,
        default=timezone.now)
    last_sent_at = models.DateTimeField(
        null=True,
        blank=True)

    class Meta:
        verbose_name = _(u'Notification message')
        verbose_name_plural = _(u'Notifications messages')
        #app_label = 'notifications'
        #db_table = 'ios_notifications_notification'

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

    def save(self, *args, **kwargs):
        """
            When images are set, they will be resized to mobile size (64x64),
            then, resource will detect the client and returns the proper
            picture
        """
        try:
            if self.picture and not self.picture._committed:
                file_name = self.picture.name.rpartition('/')[-1]
                thumb_handle, thumb = reduce_image(self.picture, (320, 132))
                # convert to simpleupladedfile class to assign to imagefield
                suf = SimpleUploadedFile(
                    file_name, thumb_handle.read(),
                    content_type='image/%s' % thumb.format)
                self.picture_mobile.save(
                    file_name, suf, save=False)
        except IOError:
            pass
        try:
            if self.square_picture and not self.square_picture._committed:
                file_name = self.square_picture.name.rpartition('/')[-1]
                thumb_handle, thumb = reduce_image(
                    self.square_picture, (64, 64))
                # convert to simpleupladedfile class to assign to imagefield
                suf = SimpleUploadedFile(
                    file_name, thumb_handle.read(),
                    content_type='image/%s' % thumb.format)
                self.square_picture_mobile.save(
                    file_name, suf, save=False)
        except IOError:
            pass
        return super(Notification, self).save(*args, **kwargs)


class Device(models.Model):
    """
    Represents an iOS device with unique token.
    """
    token = CharNullField(
        max_length=256, unique=True, blank=True, null=True, default=None)
    is_active = models.BooleanField(default=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, related_name='devices')
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

    class Meta:
        verbose_name = _(u'IOS device')
        verbose_name_plural = _(u'IOS devices')
        app_label = 'notifications'
        db_table = 'ios_notifications_device'

    def __unicode__(self):
        return u'IOS Device %s' % self.token


class AndroidDevice(models.Model):
    token = CharNullField(
        max_length=256, unique=True, blank=True, null=True, default=None)
    is_active = models.BooleanField(default=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        related_name='android_devices')

    deactivated_at = models.DateTimeField(
        null=True,
        blank=True)
    added_at = models.DateTimeField(
        auto_now_add=True,
        default=timezone.now)
    last_notified_at = models.DateTimeField(
        null=True,
        blank=True)

    class Meta:
        verbose_name = _(u'Android device')
        verbose_name_plural = _(u'Android devices')
        app_label = 'notifications'
        db_table = 'ios_notifications_androiddevice'

    def __unicode__(self):
        return u'Android Device %s' % self.token


class FeedbackService(APNService):
    """
    The service provided by Apple to inform you of devices which no longer
    have your app installed and to which notifications have failed a number
    of times. Use this class to check the feedback service and deactivate
    any devices it informs you about.

    https://developer.apple.com/library/ios/#documentation/NetworkingInternet/Conceptual/RemoteNotificationsPG/CommunicatingWIthAPS/CommunicatingWIthAPS.html#//apple_ref/doc/uid/TP40008194-CH101-SW3
    """

    PORT = 2196
    fmt = '!lh32s'
    hostname = settings.IOS_FEEDBACK_HOSTNAME

    def __init__(self, *args, **kwargs):
        self.connection = kwargs.get('connection', None)
        self.pool = kwargs.get('pool', None)
        self.certfile = kwargs.get('certfile', settings.IOS_CERT)

    def call(self):
        """
        Calls the feedback service and deactivates any devices
        the feedback service mentions.
        """
        if self.connect():
            with self.pool.get_socket() as connection:
                device_tokens = []
                while True:
                # 38 being the length in bytes of the binary format feedback tuple.
                    data = connection.recv(38)
                    if not data:
                        break
                    timestamp, token_length, token = struct.unpack(
                        self.fmt, data)
                    device_token = hexlify(token)
                    device_tokens.append(device_token)
                devices = Device.objects.filter(
                    token__in=device_tokens).delete()
                # self.disconnect()
                return devices

    def __unicode__(self):
        return u'FeedbackService %s' % self.name

    class Meta:
        unique_together = ('name', 'hostname')
