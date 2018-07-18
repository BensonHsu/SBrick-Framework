import json
from random import randrange

# libuv
import pyuv as uv

# mqtt client
import paho.mqtt.client as Mqtt

REQ_RESP_DONE = 0
REQ_RESP_CONTINUE = 1
REQ_RESP_TIMEOUT = 2
REQ_RESP_ERROR = 4

class M2mipc(Mqtt.Client):
    class ServerSession:
        def __init__(self, client, userdata, resp_topic, req_msg, handle):
            self._client = client
            self._userdata = userdata
            self._resp_topic = resp_topic
            self._req_msg = req_msg
            self._handle = handle

        def send_response(self, data, rr_status=REQ_RESP_DONE):
            msg = {
                "status": rr_status,
                "resp_msg": data
            }
            try:
                self._client.publish(self._resp_topic, json.dumps(msg))
            except:
                """ Silently drop if json dump failed """
                return REQ_RESP_ERROR

            return rr_status

        def handle_req(self):
            return self._handle(self, self._userdata, self._req_msg)

    class ClientCookie:
        def __init__(self, client, userdata, topic, handle, timeout):
            self._client = client
            self._userdata = userdata
            self._req_topic = topic + "/" + str(randrange(10000, 99999))
            self._resp_topic = self._req_topic.replace("rr", "rr_resp")
            self._handle = handle
            self._timeout = timeout
            self._msg = None

            client.subscribe(self._resp_topic)

        def _on_req_timeout(self, timer):
            self._handle(REQ_RESP_TIMEOUT, self._userdata, self._msg['req_msg'])
            self._client.delete_request(self)

        def __del__(self):
            self._client.unsubscribe(self._resp_topic)
            self._timer.stop()

        def stop_timer(self):
            self._timer.stop()

        def send(self, msg, rr_status=REQ_RESP_DONE):
            self._msg = {
                'status': rr_status,
                'req_msg': msg,
                'resp_topic': self._resp_topic
            }
            try:
                payload = json.dumps(self._msg)
            except:
                """ Silently drop if json dump failed """
                return REQ_RESP_ERROR

            if rr_status == REQ_RESP_DONE and self._timeout > 0:
                self._timer = uv.Timer(self._client._uv_loop)
                self._timer.data = self
                self._timer.start(self._on_req_timeout, self._timeout, 0)

            self._client.publish(self._req_topic, payload)
            return rr_status

        @property
        def resp_topic(self):
            return self._resp_topic

        @property
        def timeout(self):
            return self._timeout

        def handle_resp(self, status, req_msg):
            return self._handle(status, self._userdata, req_msg)

    def __init__(self, name, uv_loop):
        self._uv_loop = uv_loop
        self._reg_servers = {}
        self._req_waits = []
        self._reg_subscribes = {}

        super(M2mipc, self).__init__(name, True, self, Mqtt.MQTTv31)
        self.on_message = self._on_mqtt_message

    def connect(self, broker_ip, broker_port=1883):
        super(M2mipc, self).connect(broker_ip, broker_port)

        if self.socket():
            loop = self._uv_loop
            poll = uv.Poll(loop, self.socket().fileno())
            poll.start(uv.UV_READABLE, self._on_uv_poll)
            self._uv_poll = poll
    
            timer  = uv.Timer(loop)
            timer.start(self._on_uv_timer, 1, 1)
            self._uv_timer = timer
        else:
            raise Exception("Connect to broker failed.")
    
    def disconnect(self):
        super(M2mipc, self).disconnect()
        self._uv_poll.stop()
        self._uv_timer.stop()

    def register_subscribe(self, topic, userdata, on_subscribe):
        subs = self._reg_subscribes
        key = topic
        data = (userdata, on_subscribe)
        subs[key] = data
        self.subscribe(topic)

    def register_server(self, topic, userdata, req_handle):
        regs = self._reg_servers
        key = topic
        server_topic = topic + "/#"
        data = (userdata, req_handle, server_topic)
        regs[key] = data
        self.subscribe(server_topic)

    def unregister_server(self, topic):
        regs = self._reg_servers
        data = regs[topic]
        if data:
            self.unsubscribe(data[2])
        regs[topic] = None
    
    def prepare_request(self, topic, userdata, resp_handle, timeout=0):
        cookie = self._gen_cookie(topic, userdata, resp_handle, timeout)
        self._req_waits.append(cookie)
        return cookie

    def _on_uv_poll(self, handle, events, errorno):
        try:
            if events & uv.UV_READABLE:
                self.loop_read(100)
            if self.want_write():
                self.loop_write(100)
        except KeyboardInterrupt:
            handle.stop()
            self._uv_idle.stop()

    def _on_uv_timer(self, handle):
        try:
            if self.want_write():
                self.loop_write(100)
            self.loop_misc()
        except KeyboardInterrupt:
            handle.stop()
            self._uv_poll.stop()

    def _on_mqtt_message(self, rr, agent, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8", "ignore"))
        except:
            """ Silently drop if json load failed """
            return

        """ As a req-resp server, handle incoming requests """
        for server in rr._matched_server(msg.topic):
            session = rr._gen_session(server, payload)
            while REQ_RESP_CONTINUE == session.handle_req():
                pass
            del session
            
            return

        """ As a req-resp client, handle respones from server """
        for cookie in rr._matched_response(msg.topic):

            cookie.handle_resp(payload['status'], payload['resp_msg'])

            if REQ_RESP_DONE == payload['status']:
                if cookie.timeout > 0:
                    cookie.stop_timer()
                self._req_waits.remove(cookie)
                del cookie

            return

        """ As a subscribe client, handle subscriber """
        for subs in rr._match_subscriber(msg.topic):
            subs[1](rr, agent, msg.topic, payload)

            return

    def _match_subscriber(self, sub_topic):
        subs = self._reg_subscribes
        matched = []
        for topic, data in subs.items():
            if Mqtt.topic_matches_sub(topic, sub_topic):
                matched.append(data)

        return matched

    def _matched_server(self, req_topic):
        regs = self._reg_servers
        matched = []
        for topic, data in regs.items():
            if Mqtt.topic_matches_sub(data[2], req_topic):
                matched.append(data)

        return matched

    def _gen_session(self, server, msg):
        return self.ServerSession(
            client=self,
            userdata=server[0],
            handle=server[1],
            resp_topic=msg['resp_topic'],
            req_msg=msg['req_msg'])

    def _gen_cookie(self, topic, userdata, handle, timeout):
        return self.ClientCookie(
            client=self,
            topic=topic,
            userdata=userdata,
            handle=handle,
            timeout=timeout)
    
    def _matched_response(self, resp_topic):
        reqs = self._req_waits
        matched = []
        for cookie in reqs:
            if cookie.resp_topic == resp_topic:
                matched.append(cookie)

        return matched

    def delete_request(self, req_cookie):
        self._req_waits.remove(req_cookie)

