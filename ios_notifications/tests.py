# -*- coding: utf-8 -*-
import subprocess
import time
import struct
import os
import datetime
from gevent.server import StreamServer

from django.test import TestCase
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User
from django.http import HttpResponseNotAllowed
from django.conf import settings
from django.core import management

from ios_notifications.models import (APNService,
    Device, Notification, NotificationPayloadSizeExceeded)

TOKEN = '0fd12510cfe6b0a4a89dc7369c96df956f991e66131dab63398734e8000d0029'
TEST_PEM = os.path.abspath(os.path.join(os.path.dirname(__file__), 'test.pem'))

SSL_SERVER_COMMAND = (
    'openssl', 's_server', '-accept', '2195', '-cert', TEST_PEM)


def handle_echo(sock, address):
    print 'new connection!'

test_server_proc = StreamServer(
    ('', 2195), handle_echo,
    certfile=os.path.normpath(
        os.path.join(os.path.dirname(__file__), 'test.pem')))
test_server_proc.start()


class APNServiceTest(TestCase):
    def setUp(self):
        time.sleep(0.5)  # Wait for test server to be started

        self.service = APNService(
            hostname='127.0.0.1', certfile=os.path.normpath(
                os.path.join(os.path.dirname(__file__), 'test.pem')))
        self.device = Device.objects.create(token=TOKEN)
        self.notification = Notification.objects.create(
            message='Test message')

    def test_connection_to_remote_apn_host(self):
        self.assertTrue(self.service.connect())
        #self.service.disconnect()

    def test_invalid_payload_size(self):
        n = Notification(message='.' * 260)
        self.assertRaises(
            NotificationPayloadSizeExceeded, self.service.get_payload, n)

    def test_payload_packed_correctly(self):
        fmt = self.service.fmt
        payload = self.service.get_payload(self.notification)
        msg = self.service.pack_message(payload, self.device)
        unpacked = struct.unpack(fmt % len(payload), msg)
        self.assertEqual(unpacked[-1], payload)

    def test_pack_message_with_invalid_device(self):
        self.assertRaises(TypeError, self.service.pack_message, None)

    def test_can_connect_and_push_notification(self):
        self.assertIsNone(self.notification.last_sent_at)
        self.assertIsNone(self.device.last_notified_at)
        self.service.push_notification_to_devices(
            self.notification, [self.device.token])
        self.assertIsNotNone(self.notification.last_sent_at)
        self.assertIsNotNone(
            Device.objects.get(pk=self.device.id).last_notified_at)

    def tearDown(self):
        test_server_proc.stop()


class ManagementCommandPushNotificationTest(TestCase):
    def setUp(self):
        self.started_at = datetime.datetime.now()
        time.sleep(0.5)  # Wait for test server to be started

        self.service = APNService(
            hostname='127.0.0.1', certfile=os.path.normpath(
                os.path.join(os.path.dirname(__file__), 'test.pem')))
        self.device = Device.objects.create(token=TOKEN)
        self.notification = Notification.objects.create(
            message='Test message')

    def test_call_push_ios_notification_command(self):
        msg = 'some message'
        management.call_command(
            'push_ios_notification',
            **{'message': msg, 'service': self.service.id, 'verbosity': 0})
        self.assertTrue(Notification.objects.filter(
            message=msg).exists())

    def tearDown(self):
        test_server_proc.stop()


# class ManagementCommandCallFeedbackService(TestCase):
#     pass
