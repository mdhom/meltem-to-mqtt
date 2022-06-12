import argparse
import logging
import asyncio
import json
import time
import serial
import threading
from enum import Enum
from concurrent.futures._base import CancelledError

import minimalmodbus

from .__version import __version__
from .__mqtt import MqttClient

LOGGER = logging.getLogger("meltem-to-mqtt")

DEFAULT_ARGS = {
    "loglevel": "WARNING",
    "interval": 1.0,
    "mqttport": 1883,
    "mqttkeepalive": 60,
    "mqttbasetopic": "meltem/",
}


def main():
    try:
        loop = asyncio.get_event_loop()
        runner = Meltem2MQTT()
        loop.run_until_complete(runner.run(loop))
        loop.close()
    except KeyboardInterrupt:
        pass


class MeltemMode(Enum):
    off = 1
    manual_balanced = 2
    intensive = 3
    humidity_controlled = 4
    co2_controlled = 5
    automatic = 6
    manual_unbalanced = 7
    inconsistent = 8


class Meltem2MQTT:
    def __init__(self) -> None:
        mqtt = None  # type: MqttClient
        loop = None  # type: asyncio.AbstractEventLoop
        bus = None  # type: minimalmodbus.Instrument
        self.lock = threading.Lock()

    def __add_from_config(self, cmdArgs: dict, config: dict, name: str):
        if name in config:
            setattr(cmdArgs, name, config[name])

    async def run(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        parser = argparse.ArgumentParser(prog="meltem-to-mqtt", description="Commandline Interface to interact with E3/DC devices")
        parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
        parser.add_argument("--releaseName", type=str, dest="releaseName", help="Name of the current release")
        parser.add_argument("--configFile", type=str, dest="configFile", help="File where config is stored (JSON)")
        parser.add_argument("--loglevel", type=str, dest="loglevel", help='Minimum log level, DEBUG/INFO/WARNING/ERROR/CRITICAL"', default=DEFAULT_ARGS["loglevel"])
        parser.add_argument("--interval", type=float, dest="interval", help="Interval in seconds in which E3/DC data is requested. Minimum: 1.0", default=DEFAULT_ARGS["interval"])

        parser.add_argument("--mqtt-broker", type=str, dest="mqttbroker", help="Address of MQTT Broker to connect to")
        parser.add_argument("--mqtt-port", type=int, dest="mqttport", help="Port of MQTT Broker. Default is 1883 (8883 for TLS)", default=DEFAULT_ARGS["mqttport"])
        parser.add_argument("--mqtt-clientid", type=str, dest="mqttclientid", help="Id of the client. Default is a random id")
        parser.add_argument("--mqtt-keepalive", type=int, dest="mqttkeepalive", help="Time between keep-alive messages", default=DEFAULT_ARGS["mqttkeepalive"])
        parser.add_argument("--mqtt-username", type=str, dest="mqttusername", help="Username for MQTT broker")
        parser.add_argument("--mqtt-password", type=str, dest="mqttpassword", help="Password for MQTT broker")
        parser.add_argument("--mqtt-basetopic", type=str, dest="mqttbasetopic", help="Base topic of mqtt messages", default=DEFAULT_ARGS["mqttbasetopic"])

        args = parser.parse_args()

        if args.configFile is not None:
            with open(args.configFile) as f:
                config = json.load(f)
            self.__add_from_config(args, config, "loglevel")
            self.__add_from_config(args, config, "interval")

            self.__add_from_config(args, config, "mqttbroker")
            self.__add_from_config(args, config, "mqttport")
            self.__add_from_config(args, config, "mqttclientid")
            self.__add_from_config(args, config, "mqttkeepalive")
            self.__add_from_config(args, config, "mqttusername")
            self.__add_from_config(args, config, "mqttpassword")
            self.__add_from_config(args, config, "mqttbasetopic")

        valid_loglevels = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
        if args.loglevel not in valid_loglevels:
            print(f'Invalid log level given: {args.loglevel}, allowed values: {", ".join(valid_loglevels)}')
            return

        logging.basicConfig(level=args.loglevel)

        LOGGER.debug("Starting!")
        LOGGER.debug(f"Version: {__version__}")
        if args.releaseName is not None:
            LOGGER.debug(f"Release name: {args.releaseName}")

        if args.mqttbroker is None:
            LOGGER.error(f"no mqtt broker given")
            return
        if float(args.interval) < 1:
            LOGGER.error(f"interval must be >= 1")
            return

        try:
            self.mqtt = MqttClient(LOGGER, self.loop, args.mqttbroker, args.mqttport, args.mqttclientid, args.mqttkeepalive, args.mqttusername, args.mqttpassword, args.mqttbasetopic)
            await self.mqtt.start()
            self.mqtt.subscribe_to("/mode/set", self.__on_set_mode)
            self.mqtt.subscribe_to("/register/write", self.__on_write_register)
            self.mqtt.subscribe_to("/register/read", self.__on_read_register)

            self.bus = minimalmodbus.Instrument("/dev/ttyUSB0", 1)
            self.bus.serial.parity = serial.PARITY_EVEN
            print(f"address={self.bus.address}")
            print(f"mode={self.bus.mode}")

            # self.bus.write_register(42003,  500, functioncode=6)
            # print(self.bus.read_register(42003))

            last_data_json = ""
            last_cycle = 0.0
            while True:
                await asyncio.sleep(max(0, args.interval - (time.time() - last_cycle)))
                last_cycle = time.time()

                if not self.mqtt.is_connected:
                    LOGGER.error(f"mqtt not connected")
                    continue

                try:

                    self.lock.acquire()
                    try:
                        # print(f'CO2start={self.__read_uint8(42003)}')
                        # print(f'CO2min={self.__read_uint8(42004)}')
                        # print(f'CO2max={self.__read_uint8(42005)}')
                        data = {
                            "mode": self.__read_mode().name,
                            "error": self.__read_uint8(41016),
                            "frost_protection_active": self.__read_uint8(41018),
                            "temp_outdoor_out": self.__read_float(41000),  # Fortlufttemperatur
                            "temp_outdoor_in": self.__read_float(41002),  # Außenlufttemperatur
                            "temp_room_out": self.__read_float(41004),  # Ablufttemperatur
                            "temp_room_in": self.__read_float(41009),  # Zulufttemperatur
                            "humidity_out": self.__read_uint16(41006),
                            "humidity_in": self.__read_uint16(41011),
                            "co2_out": self.__read_uint16(41007),
                            "voc_in": self.__read_uint8(41013),
                            "throughput_out": self.__read_uint8(41020),
                            "throughput_in": self.__read_uint8(41021),
                            "filter_change_needed": self.__read_uint8(41017),
                            "filter_time_remaining": self.__read_uint16(41027),
                            # 'operating_hours_device':   self.__read_uint32(41030),
                            # 'operating_hours_motors':   self.__read_uint32(41032),
                        }

                        temperature_difference_inside_outside = abs(data["temp_room_out"] - data["temp_outdoor_in"])
                        if temperature_difference_inside_outside != 0:
                            temperature_difference_inlet = abs(data["temp_outdoor_in"] - data["temp_room_in"])
                            data["heatexchanger_efficiency"] = temperature_difference_inlet / temperature_difference_inside_outside * 100.0

                        data_json = json.dumps(data)
                        if data_json != last_data_json:
                            # print(data)
                            self.mqtt.publish(f"live", data)
                            last_data_json = data_json
                    finally:
                        self.lock.release()

                except minimalmodbus.NoResponseError:
                    LOGGER.error("no response on ModBus")
                except minimalmodbus.InvalidResponseError:
                    LOGGER.error("invalid response on ModBus")

        except KeyboardInterrupt:
            pass  # do nothing, close requested
        except CancelledError:
            pass  # do nothing, close requested
        except Exception as e:
            LOGGER.exception(f"exception in main loop")
        finally:
            LOGGER.info(f"shutdown requested")
            await self.mqtt.stop()

    def __on_write_register(self, client, userdata, msg):
        address = getattr(msg.payload, "address", None)
        if address == None:
            LOGGER.error('no value for "address" provided')
            return
        value = getattr(msg.payload, "value", None)
        if value == None:
            LOGGER.error('no value for "value" provided')
            return
            
        self.lock.acquire()
        try:
            self.bus.write_register(address, value, functioncode=6)
        except minimalmodbus.NoResponseError:
            LOGGER.error("no response on ModBus")
        except minimalmodbus.InvalidResponseError:
            LOGGER.error("invalid response on ModBus")
        finally:
            self.lock.release()

    def __on_read_register(self, client, userdata, msg):
        address = getattr(msg.payload, "address", None)
        if address == None:
            LOGGER.error('no value for "address" provided')
            return
            
        self.lock.acquire()
        try:
            value = self.bus.read_register(address)
        except minimalmodbus.NoResponseError:
            LOGGER.error("no response on ModBus")
        except minimalmodbus.InvalidResponseError:
            LOGGER.error("invalid response on ModBus")
        finally:
            self.lock.release()

        self.mqtt.publish(f"register/{address}", value)

    def __on_set_mode(self, client, userdata, msg):
        requested_mode = getattr(msg.payload, "mode", None)
        if requested_mode == None:
            LOGGER.error('no value for "requested_mode" provided')
            return

        if requested_mode == MeltemMode.off.name:
            write_data = {41120: 1, 41132: 0}
        elif requested_mode == MeltemMode.manual_balanced.name:
            throughput = getattr(msg.payload, "throughput")
            if throughput is None:
                LOGGER.error('no value for "throughput" provided')
                return
            if throughput < 0 or throughput > 100:
                LOGGER.error(f"invalid throughput provided ({throughput}). Throughput must be between 0 and 100, unit is m³/h.")
                return
            value = throughput / 100.0 * 200.0  # convert to 0-200 range needed in protocol
            write_data = {41120: 3, 41121: value, 41132: 0}
        elif requested_mode == MeltemMode.intensive.name:
            write_data = {41120: 3, 41121: 227, 41132: 0}
        elif requested_mode == MeltemMode.humidity_controlled.name:
            write_data = {41120: 2, 41121: 112, 41132: 0}
        elif requested_mode == MeltemMode.co2_controlled.name:
            write_data = {41120: 2, 41121: 144, 41132: 0}
        elif requested_mode == MeltemMode.automatic.name:
            write_data = {41120: 2, 41121: 16, 41132: 0}
        elif requested_mode == MeltemMode.manual_unbalanced.name:
            throughput_in = getattr(msg.payload, "throughput_in")
            throughput_out = getattr(msg.payload, "throughput_out")
            if throughput_in is None:
                LOGGER.error("no throughput_in provided")
                return
            if throughput_in < 0 or throughput_in > 100:
                LOGGER.error(f"invalid throughput_in provided ({throughput_in}). Throughput must be between 0 and 100, unit is m³/h.")
                return
            if throughput_out is None:
                LOGGER.error("no throughput_out provided")
                return
            if throughput_out < 0 or throughput_out > 100:
                LOGGER.error(f"invalid throughput_out provided ({throughput_out}). Throughput must be between 0 and 100, unit is m³/h.")
                return

            value_in = throughput_in / 100.0 * 200.0  # convert to 0-200 range needed in protocol
            value_out = throughput_out / 100.0 * 200.0  # convert to 0-200 range needed in protocol

            write_data = {41120: 4, 41121: value_in, 41122: value_out, 41132: 0}
        else:
            LOGGER.error('invalid value for "requested_mode" provided')
            return

        self.lock.acquire()

        try:
            for key, value in write_data.items():
                self.bus.write_register(key, value, functioncode=6)
        finally:
            self.lock.release()

    def __read_mode(self) -> MeltemMode:
        register1 = self.bus.read_register(41120)
        if register1 == 1:
            return MeltemMode.off
        elif register1 == 4:
            return MeltemMode.manual_unbalanced
        elif register1 == 3:
            register2 = self.bus.read_register(41121)
            if register2 == 227:
                return MeltemMode.intensive
            elif register2 >= 0 and register2 <= 200:
                return MeltemMode.manual_balanced
            else:
                LOGGER.error(f"inconsistent register2 value {register2}")
                return MeltemMode.inconsistent
        elif register1 == 2:
            register2 = self.bus.read_register(41121)
            if register2 == 112:
                return MeltemMode.humidity_controlled
            elif register2 == 144:
                return MeltemMode.co2_controlled
            elif register2 == 16:
                return MeltemMode.automatic
            else:
                LOGGER.error(f"inconsistent register2 value {register2}")
                return MeltemMode.inconsistent
        else:
            # LOGGER.error(f'inconsistent register1 value {register1}')
            return MeltemMode.inconsistent

    def __read_uint8(self, register_address: int):
        return self.bus.read_register(register_address)

    def __read_uint16(self, register_address: int):
        return self.bus.read_register(register_address)

    def __read_uint32(self, register_address: int):
        return self.bus.read_long(register_address)

    def __read_float(self, register_address: int):
        return self.bus.read_float(register_address, byteorder=minimalmodbus.BYTEORDER_LITTLE_SWAP)
