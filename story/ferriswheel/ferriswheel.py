import time
import sys
import random
from lib.sbrick_m2mipc import SbrickIpcClient

# sbrick setting
SBRICK_MAC = '88:6B:0F:23:7B:81'
SBRICK_CHANNEL = '01'
EXEC_TIME = 10    # seconds

def signal_cb(handl, num):
    print("Receive SIGINT signal")
    client.stop()

if __name__ == '__main__':

    client = SbrickIpcClient(broker_ip='127.0.0.1', broker_port=1883)
    client.connect()

    # client.rr_get_adc(sbrick_id=SBRICK_MAC, timeout=10)
    # response = client.json_response
    
    duration = EXEC_TIME
    exec_time_map = {
        'FF': duration,
        'EF': duration,
        'DF': duration,
        'CF': duration,
        'BF': duration
    }
    power_list = ['CF', 'BF', 'AF', '9F', '8F']
    for i in range(0,3):
        direction = '00' if 0 == random.randint(0,1) else '01'
        power = random.choice(power_list)
        exec_time = exec_time_map.get(power, duration)
        client.publish_drive(sbrick_id=SBRICK_MAC,
                             channel=SBRICK_CHANNEL,
                             direction = direction,
                             power=power,
                             exec_time=exec_time)
        time.sleep(exec_time)

    client.disconnect()

    sys.exit(0)
