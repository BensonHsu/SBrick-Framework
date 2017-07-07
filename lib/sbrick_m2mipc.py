import sys
import json
import pyuv
import logging
from bluepy.btle import Peripheral, BTLEException
from lib.m2mipc import M2mipc, REQ_RESP_DONE, REQ_RESP_TIMEOUT
from lib.sbrick_api import ScanAPI, SbrickAPI
from lib.sbrick_protocol import SbrickProtocol


class SbrickIpcServer():
    def __init__(self, logger, broker_ip, broker_port, loop):
        self._loop = loop
        self._logger = logger
        self._broker_ip = broker_ip
        self._broker_port = broker_port
        
        self._protocol = SbrickProtocol()

        # sbrick_id -> sbrick object
        self._sbrick_map = {}


    def connect(self, sbrick_list):
        # connect to MQTT broker
        m2m = M2mipc('sbrick_server', self._loop)
        m2m.on_connect = self._on_mqtt_connect
        m2m.connect(self._broker_ip, self._broker_port)
        self._m2mipc = m2m

        # connect to sbrick
        for sbrick_id in sbrick_list:
            sbrick = SbrickAPI(logger=self._logger, dev_mac=sbrick_id)
            sbrick.disconnect_ex()
            sbrick.connect()
            self._sbrick_map[sbrick_id] = sbrick


    def disconnect(self):
        self._logger.info('Disconnect from mosquitto broker {}:{}'.format(self._broker_ip, self._broker_port))
        self._m2mipc.disconnect()

        for sbrick_id, sbrick in self._sbrick_map.items():
            sbrick.disconnect()


    def _get_sbrick(self, sbrick_id):
        obj = self._sbrick_map.get(sbrick_id, None)
        if None == obj:
            self._logger.error('Wrong SBrick MAC ({})'.format(sbrick_id))
        return obj


    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if 0 == rc:
            self._logger.info('Connect to mosquitto broker {}:{}'.format(self._broker_ip, self._broker_port))
            self._m2mipc.register_subscribe(self._protocol.gen_sp_topic('drive'), self, self._on_subscribe_drive)
            self._m2mipc.register_subscribe(self._protocol.gen_sp_topic('stop'), self, self._on_subscribe_stop)

            self._m2mipc.register_server(self._protocol.gen_rr_topic('get_service'), self, self._on_rr_get_service)
            self._m2mipc.register_server(self._protocol.gen_rr_topic('get_adc'), self, self._on_rr_get_adc)
            self._m2mipc.register_server(self._protocol.gen_rr_topic('get_general'), self, self._on_rr_get_general)


    def _on_rr_get_service(self, request, userdata, json_msg):
        message = json.loads(json_msg)
        self._logger.debug('Accept get_service() event: {}'.format(message))
        sbrick = self._get_sbrick(message['sbrick_id'])
        services = sbrick.get_info_service() if sbrick else self._protocol.gen_rr_get_service_response(ret_code=SbrickProtocol.CODE_ERR_PARM, msg={})
        rc = request.send_response(services)
        return rc


    def _on_rr_get_adc(self, request, userdata, json_msg):
        message = json.loads(json_msg)
        self._logger.debug('Accept get_adc() event: {}'.format(message))
        sbrick = self._get_sbrick(message['sbrick_id'])
        adc = sbrick.get_info_adc() if sbrick else self._protocol.gen_rr_get_adc_response(ret_code=SbrickProtocol.CODE_ERR_PARM, msg={})
        rc = request.send_response(adc)
        return rc


    def _on_rr_get_general(self, request, userdata, json_msg):
        message = json.loads(json_msg)
        self._logger.debug('Accept get_general() event: {}'.format(message))
        sbrick = self._get_sbrick(message['sbrick_id'])
        general = sbrick.get_info_general() if sbrick else self._protocol.gen_rr_get_general_response(ret_code=SbrickProtocol.CODE_ERR_PARM, msg={})
        rc = request.send_response(general)
        return rc


    def _on_subscribe_drive(self, client, userdata, topic, msg):
        self._logger.debug('Accept drive() event: {}'.format(msg))
        sbrick = self._get_sbrick(msg['sbrick_id'])
        if not sbrick:
            return
        # TODO: validate param
        sbrick.drive(channel=msg['channel'], direction=msg['direction'], power=msg['power'], exec_time=msg['exec_time'])


    def _on_subscribe_stop(self, client, userdata, topic, msg):
        self._logger.debug('Accept sopt() evnet: {}'.format(msg))
        # TODO: validate param
        sbrick = self._sbrick_map[msg['sbrick_id']]
        sbrick.stop(channels=msg['channels'])



class SbrickIpcClient():
    def __init__(self, logger=None, broker_ip='127.0.0.1', broker_port=1883):
        self._loop = pyuv.Loop.default_loop()
        """ Important. The base time of event loop is cahced at the earliest running """
        self._loop.update_time()
        self._broker_ip = broker_ip
        self._broker_port = broker_port
        self._json_response = None
        self._protocol = SbrickProtocol()

        self._logger = logger if logger else self._set_logger()


    def _set_logger(self):
        logger = logging.getLogger('SBrick_Client')
        stream_handler = logging.StreamHandler(sys.stdout)
        log_format = "%(asctime)s [%(name)s.%(levelname)s] %(message)s"
        stream_handler.setFormatter(logging.Formatter(fmt=log_format))
        logger.setLevel(logging.INFO)
        logger.addHandler(stream_handler)
        return logger


    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if 0 == rc:
            self._logger.info('Connect to mosquitto broker {}:{}'.format(self._broker_ip, self._broker_port))


    def connect(self): 
        m2m = M2mipc('sbrick_client', self._loop)
        m2m.on_connect = self._on_mqtt_connect
        m2m.connect(self._broker_ip, self._broker_port)
        self._m2mipc = m2m


    def disconnect(self):
        self._logger.info('Disconnect from mosquitto broker {}:{}'.format(self._broker_ip, self._broker_port))
        self._m2mipc.disconnect()


    def publish_drive(self, sbrick_id, channel, direction, power, exec_time):
        topic = self._protocol.gen_sp_topic('drive')
        json_payload = json.dumps(self._protocol.gen_sp_drive(sbrick_id, channel, direction, power, exec_time))
        self._m2mipc.publish(topic, json_payload)


    def publish_stop(self, sbrick_id, channel_list):
        topic = self._protocol.gen_sp_topic('stop')
        json_payload = json.dumps(self._protocol.gen_sp_stop(sbrick_id, channel_list))
        self._m2mipc.publish(topic, json_payload)


    def rr_get_service(self, sbrick_id, timeout):
        topic = self._protocol.gen_rr_topic('get_service')
        json_payload = json.dumps(self._protocol.gen_rr_request(sbrick_id))
        client = self._m2mipc.prepare_request(topic, topic, self._on_rr_resp, timeout)
        client.send(json_payload)
        self._loop.run()
        return self._json_response
        

    def rr_get_adc(self, sbrick_id, timeout):
        topic = self._protocol.gen_rr_topic('get_adc')
        json_payload = json.dumps(self._protocol.gen_rr_request(sbrick_id))
        client = self._m2mipc.prepare_request(topic, topic, self._on_rr_resp, timeout)
        client.send(json_payload)
        self._loop.run()
        return self._json_response


    def rr_get_general(self, sbrick_id, timeout):
        topic = self._protocol.gen_rr_topic('get_general')
        json_payload = json.dumps(self._protocol.gen_rr_request(sbrick_id))
        client = self._m2mipc.prepare_request(topic, topic, self._on_rr_resp, timeout)
        client.send(json_payload)
        self._loop.run()
        return self._json_response


    def _on_rr_resp(self, status, userdata, msg):
        if REQ_RESP_DONE == status:
            ret_code =  msg['ret_code'] if 'ret_code' in msg else SbrickProtocol.CODE_SUCCESS
        elif REQ_RESP_TIMEOUT == status:
            msg = {}
            ret_code = SbrickProtocol.CODE_ERR_TIMEOUT

        if userdata == self._protocol.gen_rr_topic('get_adc'):
            response = self._protocol.gen_rr_get_adc_response(ret_code=ret_code, msg=msg)
        elif userdata == self._protocol.gen_rr_topic('get_service'):
            response = self._protocol.gen_rr_get_service_response(ret_code=ret_code, msg=msg)
        elif userdata == self._protocol.gen_rr_topic('get_general'):
            response = self._protocol.gen_rr_get_general_response(ret_code=ret_code, msg=msg)

        self._json_response = json.dumps(response)

        self._loop.stop()
 

    @property
    def json_response(self):
        return self._json_response
