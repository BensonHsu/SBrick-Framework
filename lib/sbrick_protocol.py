class SbrickProtocol(object):
    def __init__(self):
        self.module = 'sbrick'
        self.version = '01'


    def gen_sp_topic(self, action):
        return "{module}/{version}/sp/{action}".format(action=action, **(self.__dict__))
    

    def gen_rr_topic(self, action):
        return "{module}/{version}/rr/{action}".format(action=action, **(self.__dict__))


    def gen_rr_request(self, sbrick_id):
        request = {'sbrick_id': sbrick_id}
        return request


    def gen_sp_drive(self, sbrick_id, channel, direction, power, exec_time):
        payload = {
            'sbrick_id': sbrick_id,
            'channel': channel,
            'direction': direction,
            'power': power,
            'exec_time': exec_time
        }
        return payload


    def gen_sp_stop(self, sbrick_id, channel_list):
        payload = {
            'sbrick_id': sbrick_id,
            'channels': channel_list
        }
        return payload


    def gen_rr_get_service_response(self, ret_code, msg):
        response = {
            'ret_code': ret_code,
            'services': msg
        }
        return response

    
    def gen_rr_get_adc_response(self, ret_code, msg):
        response = {
            'ret_code': ret_code,
            'temperature': msg.get('temperature', None),
            'voltage': msg.get('voltage', None)
        }
        return response


    def gen_rr_get_general_response(self, ret_code, msg):
        response = {
            'ret_code': ret_code,
            'is_auth': msg.get('is_auth', None),
            'auth_timeout': msg.get('auth_timeout', None),
            'brick_id': msg.get('brick_id', None),
            'watchdog_timeout': msg.get('watchdog_timeout', None),
            'thermal_limit': msg.get('thermal_limit', None),
            'is_quest_password_set': msg.get('is_quest_password_set', None),
            'power_cycle_count': msg.get('power_cycle_count', None),
            'uptime_count': msg.get('uptime_count', None)
        }
        return response



SbrickProtocol.CODE_SUCCESS = 100
SbrickProtocol.CODE_ERR_COMMON = 200
SbrickProtocol.CODE_ERR_PARM = 220
SbrickProtocol.CODE_ERR_TIMEOUT = 300
