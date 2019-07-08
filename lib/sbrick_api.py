import sys
import struct
import time
import subprocess
import shlex
from threading import Thread, Timer, Event, Lock
from bluepy.btle import Peripheral, BTLEException, Scanner, DefaultDelegate, BTLEDisconnectError
import inspect

MAGIC_FOREVER = 5566

class ScanAPI(object):
    ad_type_manufacturer = 255

    class ScanDelegate(DefaultDelegate):

        def __int__(self):
            DefaultDelegate.__init__(self)


        def handleDiscovery(self, dev, isNewDev, isNewData):
            if isNewDev:
                print("Discovered device {} ({})".format(dev.addr, dev.iface))
            elif isNewData:
                print("Received new data from {} ({})".format(dev.addr, dev.iface))


    @staticmethod
    def scan(timeout=5):
        scanner = Scanner()
        scanner.withDelegate(ScanAPI.ScanDelegate())
        devices = scanner.scan(timeout)

        for dev in devices:
            print("Device {} RSSI={} db, addrType={}, iface={}, connectable={}".format(dev.addr, dev.rssi, dev.addrType, dev.iface, dev.connectable))



class SbrickAPI(object):
    # UUID of Remote Control Commands. The Remote Control Commands characteristic allows full control over SBrick.
    rcc_uuid = '02b8cbcc-0e25-4bda-8790-a15f53e6010f'
    stop_hex = '00'
    drive_hex = '01'

    class DriveThread(Thread):
        def __init__(self, logger, sbrick, channel, direction, power):
            Thread.__init__(self)
            self._sbrick = sbrick
            self._channel = channel
            self._direction = direction
            self._power = power
            self._logger = logger

            self._stop_event = Event()
            self._timer_thd = None


        def run(self):
            self.drive()


        def drive(self):
            self.drive_channel()
            #self.break_channel()

        def stop(self):
            self._stop_event.set()
            self._timer_thd.cancel()

        def times_up(self):
            self._logger.debug('Drive action times_up {}{}{}{}'.format(SbrickAPI.drive_hex, self._channel, self._direction, self._power))
            self._stop_event.set()

        def reset_command(self, channel, direction, power):
           self._channel = channel
           self._direction = direction
           self._power = power

        def reset_timer(self, exec_time):
            if self._timer_thd:
                self._timer_thd.cancel()
            if self._stop_event:
                self._stop_event.clear()

            if MAGIC_FOREVER == exec_time:
                return
            self._timer_thd = Timer(exec_time, self.times_up)
            self._timer_thd.setName('timer_' + self._channel)
            self._timer_thd.start()


        def drive_channel(self):
            while(not self._stop_event.is_set()):
                drive_hex_string = SbrickAPI.drive_hex + self._channel + self._direction + self._power
                self.exec_command(drive_hex_string)
                # TODO: not need to sleep
                #time.sleep(0.1)
                time.sleep(1)

        def break_channel(self):
            stop_hex_string = SbrickAPI.stop_hex + self._channel
            self.exec_command(stop_hex_string)

        def exec_command(self, hex_string):
            self._logger.debug('Exec command {}'.format(hex_string))
            binary = bytes.fromhex(hex_string)
            self._sbrick.rcc_char_write_ex(binary, reconnect_do_again=False)
            #self._sbrick.rcc_char_read_ex(reconnect_do_again=False)
            

        @property
        def stop_event(self):
            return self._stop_event

        @property
        def timer_thd(self):
            return self._timer_thd

    def __init__(self, logger, dev_mac):
        self._dev_mac = dev_mac
        self._logger = logger
        self._lock = Lock()

        # bluepy is not thread-safe, must use lock to protect it
        self._blue = Peripheral()
        self._rcc_char = None

        self._channel_thread = {
            '00': None,
            '01': None,
            '02': None,
            '03': None
        }

    def __enter__(self):
        self.connect()
        return self


    def __exit__(self, type, value, traceback):
        self.disconnect()


    def _construct_new_bluetooth_object(self):
        self._lock.acquire()
        self._logger.info("Construct a new bluetooth object")
        del self._blue
        self._blue = Peripheral()
        self._lock.release()


    def connect(self):
        try:
            self._lock.acquire()
            self._logger.info('Try to connect to SBrick ({})'.format(self._dev_mac))
            # connect() is a blocking function
            self._blue.connect(self._dev_mac)
        except BTLEException as e:
            self._lock.release()
            self._logger.error('SBrick ({}): {}'.format(self._dev_mac, e.message))
            if BTLEException.DISCONNECTED == e.code:
                return False
            else:
                self._construct_new_bluetooth_object()
                self._logger.error('exit -1')
                sys.exit(-1)
        except Exception as e:
            self._lock.release()
            self._logger.error(e)    
            self._construct_new_bluetooth_object()
            self._logger.error('exit -1')
            sys.exit(-1)
        else:
            self._logger.info('Connect to SBrick ({}) successfully'.format(self._dev_mac))
        
        # Get remote control command characteristic
        try:
            self._logger.info('Get rcc characteristic')
            chars = self._blue.getCharacteristics(uuid = SbrickAPI.rcc_uuid)
        except Exception as e:
            self._lock.release()
            self._logger.error("Failed to get SBrick characteristics ({}): {}".format(SbrickAPI.rcc_uuid, e))
            self._construct_new_bluetooth_object()
            self._logger.error('exit -1')
            sys.exit(-1)
        else:
            for char in chars:
                if char.uuid == SbrickAPI.rcc_uuid:
                    self._rcc_char = char

        # Get services information
        try:
            services = self._blue.getServices()
        except Exception as e:
            self._lock.release()
            self._logger.error("Failed to get SBrick services ({}): {}".format(self._dev_mac, e))
            self._construct_new_bluetooth_object()
            self._logger.error('exit -1')
            sys.exit(-1)
        else:
            self._services = services
            self._lock.release()
            
        return True
 

    def disconnect_ex(self):
        # disconnect SBrick using bluetoothctl command
        bl_cmd = 'disconnect {}\nquit'.format(self._dev_mac)
        cmd = "echo -e '{}'".format(bl_cmd)
        p1 = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE)
        p2 = subprocess.Popen(shlex.split('bluetoothctl'), stdin=p1.stdout, stdout=subprocess.PIPE, shell=True)
        p1.stdout.close()
        p2.communicate()
        # wait 3 seconds for real disconnection, because `bluetoothctl #disconnect` is an asynchronous command
        time.sleep(3)
        

    def disconnect(self):
        self._lock.acquire()
        self._blue.disconnect()
        self._logger.info('Disconnect from SBrick({}) successfully'.format(self._dev_mac))
        self._lock.release()


    def re_connect(self):
        self._logger.info('Re-connect to SBrick ({})'.format(self._dev_mac))
        self.disconnect()
        return self.connect()


    def drive(self, channel='00', direction='00', power='f0', exec_time=1):
        # reset thread status when the thread is dead
        if self._channel_thread[channel] and not self._channel_thread[channel].is_alive():
            self._channel_thread[channel].join()
            self._channel_thread[channel] = None

        if None == self._channel_thread[channel]:
            # Create a thread for executing drive
            thd = SbrickAPI.DriveThread(self._logger, self, channel, direction, power)
            thd.setName('channel_' + channel)
            thd.reset_timer(exec_time)
            self._channel_thread[channel] = thd
            thd.start()
        else:
            self._logger.debug('Overwrite drive action')
            running_thd = self._channel_thread[channel]
            running_thd.reset_command(channel, direction, power)
            running_thd.reset_timer(exec_time)
        


    def stop(self, channels=['00']):
        # TODO: validate parameters
        self._logger.debug('Stop action')
        for channel in channels:
            thd = self._channel_thread[channel]
            if thd:
                thd.stop()
                thd.join()
                self._channel_thread[channel] = None


    def rcc_char_write_ex(self, binary, reconnect_do_again=True):
        # make sure _rcc_char exist
        self._lock.acquire()
        self._logger.debug('RCC characteristic writes binary: {}'.format(binary))
        if not self._rcc_char:
            self._lock.release()
            self._construct_new_bluetooth_object()
            if False == self.re_connect(): return False

        # write binary
        try:
            self._rcc_char.write(binary)
        except BrokenPipeError as e:
            self._lock.release()
            self._logger.error('BrokerPipeError with bluepy-helper')
            self._logger.error('exit -1')
            sys.exit(-1)
        except BTLEException as e:
            self._lock.release()
            self._logger.error('SBrick ({}): {}'.format(self._dev_mac, e.message))
            if isinstance(e, BTLEDisconnectError):
                self._construct_new_bluetooth_object()
                if False == self.re_connect(): return False
                if reconnect_do_again: self.rcc_char_write_ex(binary, reconnect_do_again=False)
            elif BTLEException.INTERNAL_ERROR == e.code and "Helper not started (did you call connect()?)" == e.message:
                self._construct_new_bluetooth_object()
                if False == self.re_connect(): return False
                if reconnect_do_again: self.rcc_char_write_ex(binary, reconnect_do_again=False)
            else:
                self._construct_new_bluetooth_object()
                self._logger.error('exit -1')
                sys.exit(-1)
        except Exception as e:
            self._lock.release()
            self._logger.error(e)
            self._construct_new_bluetooth_object()
            self._logger.error('exit -1')
            sys.exit(-1)
        else:
            self._lock.release()

        
        return True


    def rcc_char_read_ex(self, reconnect_do_again=True):
        try:
            self._lock.acquire()
            out = self._rcc_char.read()
        except BrokenPipeError as e:
            self._lock.release()
            self._logger.error('BrokerPipeError with bluepy-helper')
            self._logger.error('exit -1')
            sys.exit(-1)
        except BTLEException as e:
            self._lock.release()
            self._logger.error('SBrick ({}): {}'.format(self._dev_mac, e.message))
            if BTLEException.DISCONNECTED == e.code:
                if False == self.re_connect(): return False
                if reconnect_do_again: self.rcc_char_read_ex(reconnect_do_again=False)
            else:
                self._construct_new_bluetooth_object()
                self._logger.error('exit -1')
                sys.exit(-1)
        except Exception as e:
            self._lock.release()
            self._logger.error(e)
            self._construct_new_bluetooth_object()
            self._logger.error('exit -1')
            sys.exit(-1)
        else:
            self._lock.release()
            
        return out


    def get_info_service(self):
        self._logger.debug("Service information:")
        for s in self._services:
            self._logger.debug("  {service}, {uuid}".format(service=s, uuid=s.uuid))
            chars = s.getCharacteristics()
            for c in chars:
                self._logger.debug("    {char}, {uuid}, {proty}".format(char=c, uuid=c.uuid, proty=c.propertiesToString()))

        ret = []
        for s in self._services:
            service = {}
            service['description'] = "{}".format(s)
            service['uuid'] = s.uuid.getCommonName()
            service['characteristics'] = []
            chars = s.getCharacteristics()
            for c in chars:
                characteristic = {}
                characteristic['description'] = "{}".format(c)
                characteristic['uuid'] = c.uuid.getCommonName()
                characteristic['property'] = c.propertiesToString()
                #characteristic['value'] = c.read() if c.supportsRead() else ''
                service['characteristics'].append(characteristic)
            ret.append(service)
        self.disconnect()
        return ret


    def get_info_adc(self):
        ret = {}
        # Get temperature
        code = bytes.fromhex('0F09')
        if False == self.rcc_char_write_ex(code): return ret
        binary = self.rcc_char_read_ex()
        value = struct.unpack("<H", binary)[0]
        self._temperature = (value / 118.85795) - 160

        # Get voltage
        code = bytes.fromhex('0F08')
        if False == self.rcc_char_write_ex(code): return ret
        binary = self.rcc_char_read_ex()
        value = struct.unpack('<H', binary)[0]
        self._voltage = (value * 0.83875) / 2047.0

        self._logger.debug("ADC information:")
        self._logger.debug("  Temperature = {}".format(self._temperature))
        self._logger.debug("  Voltage = {}".format(self._voltage))

        ret['temperature'] = self._temperature
        ret['voltage'] = self._voltage
        self.disconnect()
        return ret


    def get_info_general(self):
        ret = {}
        # Get is_authenticated
        code = bytes.fromhex('03')
        if False == self.rcc_char_write_ex(code): return ret
        binary = self.rcc_char_read_ex()
        value = struct.unpack("<B", binary)[0]
        self._is_auth = value

        # Get authentication timeout
        code = bytes.fromhex('09')
        if False == self.rcc_char_write_ex(code): return ret
        binary = self.rcc_char_read_ex()
        value = struct.unpack("<B", binary)[0]
        self._auth_timeout = value * 0.1    # second

        # Get brick ID
        code = bytes.fromhex('0A')
        if False == self.rcc_char_write_ex(code): return ret
        binary = self.rcc_char_read_ex()
        value = struct.unpack("<6B", binary)
        l = list(map(lambda v: "%X" %(v), list(value)))
        self._brick_id = ' '.join(l)

        # Get watchdog timeout
        code = bytes.fromhex('0E')
        if False == self.rcc_char_write_ex(code): return ret
        binary = self.rcc_char_read_ex()
        value = struct.unpack("<B", binary)[0]
        self._watchdog_timeout = value * 0.1  # second

        # Get thermal limit
        code = bytes.fromhex('15')
        if False == self.rcc_char_write_ex(code): return ret
        binary = self.rcc_char_read_ex()
        value = struct.unpack("<H", binary)[0]
        self._thermal_limit = (value / 118.85795) - 160

        # Get PWM counter value
        code = bytes.fromhex('20')
        if False == self.rcc_char_write_ex(code): return ret
        binary = self.rcc_char_read_ex()
        value = struct.unpack("<H", binary)[0]
        self._pwm_counter_value = value

        # Get channel status
        code = bytes.fromhex('22')
        if False == self.rcc_char_write_ex(code): return ret
        binary = self.rcc_char_read_ex()
        value = struct.unpack("<7B", binary)
        self._channel_status = value

        # Get is guest password set
        code = bytes.fromhex('23')
        if False == self.rcc_char_write_ex(code): return ret
        binary = self.rcc_char_read_ex()
        value = struct.unpack("<B", binary)[0]
        self._is_quest_pw_set = value

        # Get connection parameters
        code = bytes.fromhex('25')
        if False == self.rcc_char_write_ex(code): return ret
        binary = self.rcc_char_read_ex()
        value = struct.unpack("<3H", binary)
        self._conn_param = value

        # Get release on reset
        code = bytes.fromhex('27')
        if False == self.rcc_char_write_ex(code): return ret
        binary = self.rcc_char_read_ex()
        value = struct.unpack("<B", binary)[0]
        self._ror = value

        # Get power cycle counter
        code = bytes.fromhex('28')
        if False == self.rcc_char_write_ex(code): return ret
        binary = self.rcc_char_read_ex()
        value = struct.unpack("<I", binary)[0]
        self._power_cycle_counter = value

        # Get uptime counter
        code = bytes.fromhex('29')
        if False == self.rcc_char_write_ex(code): return ret
        binary = self.rcc_char_read_ex()
        value = struct.unpack("<I", binary)[0]
        self._uptime_counter = value

        self._logger.debug("General information:")
        self._logger.debug("  Is authenticated: {}".format(self._is_auth))
        self._logger.debug("  Authentication timeout(second): {}".format(self._auth_timeout))
        self._logger.debug("  Brick ID: {}".format(self._brick_id))
        self._logger.debug("  Watchdog timeout(second): {}".format(self._watchdog_timeout))
        self._logger.debug("  Thermal limit: {}".format(self._thermal_limit))
        self._logger.debug("  PWM counter value: {}".format(self._pwm_counter_value))
        self._logger.debug("  Channel status: {}".format(self._channel_status))
        self._logger.debug("  Is guest password set: {}".format(self._is_quest_pw_set))
        self._logger.debug("  Connection parameters(ms): {}".format(self._conn_param))
        self._logger.debug("  Release on reset: {}".format(self._ror))
        self._logger.debug("  Power cycle counter: {}".format(self._power_cycle_counter))
        self._logger.debug("  Uptime counter: {}".format(self._uptime_counter))

        ret['is_auth'] = self._is_auth
        ret['auth_timeout'] = self._auth_timeout
        ret['brick_id'] = self._brick_id
        ret['watchdog_timeout'] = self._watchdog_timeout
        ret['thermal_limit'] = self._thermal_limit
        ret['is_quest_password_set'] = self._is_quest_pw_set
        ret['power_cycle_count'] = self._power_cycle_counter
        ret['uptime_count'] = self._uptime_counter
        self.disconnect()
        return ret


    def set_watchdog_timeout(self, timeout):
        """
        timeout: 0.1 seconds, 1 byte. Ragne: 0 ~ 255
        """

        self.connect()
        code = bytes.fromhex('0D') + struct.pack('<B', timeout)
        self.rcc_char_write_ex(code)
        self.disconnect()



    @property
    def blue(self):
        return self._blue

