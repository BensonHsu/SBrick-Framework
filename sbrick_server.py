import pyuv
import signal
import paho.mqtt.client as Mqtt
import logging
import argparse
import re
import sys
from lib.sbrick_api import ScanAPI, SbrickAPI
from lib.sbrick_m2mipc import SbrickIpcServer

LOG_FORMAT = "%(asctime)s [%(name)s.%(levelname)s] %(threadName)s - %(message)s"

class ServerArgParse(object):
    def __init__(self):
        self._parser = argparse.ArgumentParser()
        self._args = None


    def parse_args(self):
        parser = self._parser

        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--connect', action='store_true', help='Connect to SBrick')
        group.add_argument('--scan', action='store_true', help='Scan for getting SBrick information')

        connect = parser.add_argument_group('--connect')
        connect.add_argument('--broker-ip', type=self._ip_validation, default='127.0.0.1', help='MQTT broker ip address. Default is 127.0.0.1')
        connect.add_argument('--broker-port', type=self._port_validation, default=1883, help='MQTT broker port. Default is 1883')
        connect.add_argument('--sbrick-id', nargs='+', type=self._mac_validation, help='list of SBrick MAC to connect to')
        connect.add_argument('--log-level', type=self._log_level_validation, default='INFO', help='Log verbose level. Default is INFO. [DEBUG | INFO | WARNING | ERROR | CRITICAL]')

        scan = parser.add_argument_group('--scan')
        self._args = parser.parse_args()
        return self._args


    def _ip_validation(self, string):
        pattern = '^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
        result = re.match(pattern, string)
        if result:
            return string
        else:
            msg = "IP address format error. {}".format(string)
            raise argparse.ArgumentTypeError(msg)


    def _port_validation(self, string):
        port = int(string)
        if port < 1 or port > 65535:
            msg = "{} is out of range (1~65535)".format(string)
            raise argparse.ArgumentTypeError(msg)
        else:
            return port


    def _log_level_validation(self, string):
        levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if string.upper() in levels:
            return string
        else:
            msg = "Log level must be {}".format(levels)
            raise argparse.ArgumentTypeError(msg)


    def _mac_validation(self, string):
        # TODO
        return string



def signal_cb(handle, num):
    print("Receive SIGINT signal")
    loop.stop()
    server.disconnect()

def set_logger(level):
    logger = logging.getLogger('SBrick_Server')
    # stream handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(fmt=LOG_FORMAT))
    logger.setLevel(level)
    logger.addHandler(stream_handler)
    return logger



if __name__ == '__main__':

    """ Arguments """
    args = ServerArgParse().parse_args()

    """ Logger """
    log_level = getattr(logging, args.log_level.upper(), logging.INFO) 
    logger = set_logger(log_level)

    """ Print arguments """
    logger.info('SBrick server settings')
    for key, value in vars(args).items():
        logger.info('  {}:{}'.format(key, value))

    """ Connect or Scan SBrick """
    if args.connect:
        loop = pyuv.Loop.default_loop()

        signal_h = pyuv.Signal(loop)
        signal_h.start(signal_cb, signal.SIGINT)

        server = SbrickIpcServer(logger, args.broker_ip, args.broker_port, loop)
        server.connect(args.sbrick_id)

        loop.run()
    elif args.scan:
        ScanAPI().scan(timeout=10)
