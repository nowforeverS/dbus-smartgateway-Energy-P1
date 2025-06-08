#!/usr/bin/env python
# vim: ts=2 sw=2 et

# import normal packages
import os
import platform 
import logging
import logging.handlers
import sys
import time
import requests  # for HTTP GET
import configparser  # for config/ini file

# Import the appropriate GLib object based on Python version
if sys.version_info.major == 2:
    import gobject
else:
    from gi.repository import GLib as gobject

# our own packages from victron
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService

class DbusHomeWizzardEnergyP1Service:
    def __init__(self, paths, productname='Hsmartgateway Energy P1', connection='Home Wizzard Energy P1 HTTP JSON service'):
        config = self._getConfig()
        deviceinstance = int(config['DEFAULT']['DeviceInstance'])
        customname = config['DEFAULT']['CustomName']
        role = config['DEFAULT']['Role']

        allowed_roles = ['pvinverter', 'grid']
        if role in allowed_roles:
            servicename = 'com.victronenergy.' + role
        else:
            logging.error("Configured Role: %s is not in the allowed list", role)
            exit()

        if role == 'pvinverter':
            productid = 0xA144
        else:
            productid = 45069

        self._dbusservice = VeDbusService("{}.http_{:02d}".format(servicename, deviceinstance))
        self._paths = paths

        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unknown version, and running on Python ' + platform.python_version())
        self._dbusservice.add_path('/Mgmt/Connection', connection)
    
        # Create the mandatory objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductId', productid)
        self._dbusservice.add_path('/DeviceType', 345)  # ET340 Energy Meter
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/CustomName', customname)
        self._dbusservice.add_path('/Latency', None)
        self._dbusservice.add_path('/FirmwareVersion', 0.2)
        self._dbusservice.add_path('/HardwareVersion', 0)
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/Role', role)
        self._dbusservice.add_path('/Position', self._getP1Position())  # normally only needed for pvinverter
        self._dbusservice.add_path('/Serial', self._getP1Serial())
        self._dbusservice.add_path('/UpdateIndex', 0)
        
        # add path values to dbus
        for path, settings in self._paths.items():
            self._dbusservice.add_path(
                path, settings['initial'], gettextcallback=settings['textformat'], writeable=True, onchangecallback=self._handlechangedvalue)
    
        # last update
        self._lastUpdate = 0
    
        # add _update function 'timer'
        gobject.timeout_add(500, self._update)  # pause 500ms before the next request
        
        # add _signOfLife 'timer' to get feedback in log every 5 minutes
        gobject.timeout_add(self._getSignOfLifeInterval() * 60 * 1000, self._signOfLife)
    
    def _getP1Serial(self):
        meter_data = self._getP1Data()  
        
        if 'Equipment_Id' not in meter_data:
            raise ValueError("Response does not contain 'Equipment_Id' attribute")
        
        return meter_data['Equipment_Id']

    def _getConfig(self):
        config = configparser.ConfigParser()
        config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
        return config
 
    def _getSignOfLifeInterval(self):
        config = self._getConfig()
        value = config['DEFAULT'].get('SignOfLifeLog', 0)
        return int(value)

    def _getP1Position(self):
        config = self._getConfig()
        value = config['DEFAULT'].get('Position', 0)
        return int(value)

    def _getP1StatusUrl(self):
        config = self._getConfig()
        accessType = config['DEFAULT']['AccessType']
        
        if accessType == 'OnPremise': 
            URL = "http://%s/smartmeter/api/read" % (config['ONPREMISE']['Host'])
        else:
            raise ValueError("AccessType %s is not supported" % accessType)
        
        return URL
  
    def _getP1Data(self):
        URL = self._getP1StatusUrl()
        meter_r = requests.get(url=URL, timeout=5)
        
        # check for response
        if not meter_r.ok:
            raise ConnectionError("No response from Smart Gateway - %s" % URL)
        
        meter_data = meter_r.json()
        
        # check for Json
        if not meter_data:
            raise ValueError("Converting response to JSON failed")
        
        return meter_data
  
    def _signOfLife(self):
        logging.info("--- Start: sign of life ---")
        logging.info("Last _update() call: %s", self._lastUpdate)
        logging.info("Last '/Ac/Power': %s", self._dbusservice['/Ac/Power'])
        logging.info("--- End: sign of life ---")
        return True

    def _calculate_power_and_current(self, meter_data, phase):
        """
        Calculates power and current for a given phase.

        :param meter_data: Dictionary containing meter data.
        :param phase: String representing the phase ('l1', 'l2', or 'l3').
        :return: Tuple containing power and current values.
        """
        power_delivered_key = f'PowerDelivered_{phase}'
        power_returned_key = f'PowerReturned_{phase}'
        current_key = f'Current_{phase}'

        Power = float(meter_data.get(power_delivered_key, 0))
        if Power > 0:
            Current = float(meter_data.get(current_key, 0))
        else:
            Power = -abs(float(meter_data.get(power_returned_key, 0)))
            Current = -abs(float(meter_data.get(current_key, 0)))

        return Power, Current

    def _update(self):   
        try:
            meter_data = self._getP1Data()
            config = self._getConfig()

            phases = config['DEFAULT']['Phases']

            if phases == '1':
                # Send data to DBus for single-phase system
                self._dbusservice['/Ac/Power'] = float(meter_data['PowerDeliveredNetto'])
                self._dbusservice['/Ac/L1/Voltage'] = meter_data['Voltage_l1']
                self._dbusservice['/Ac/L1/Current'] = Current1
                self._dbusservice['/Ac/L1/Power'] = Power1
                self._dbusservice['/Ac/Energy/Forward'] = float(meter_data['PowerDelivered_total'] * 1000)
                self._dbusservice['/Ac/Energy/Reverse'] = float(meter_data['PowerReturned_total'] * 1000)
                self._dbusservice['/Ac/L1/Energy/Forward'] = float(meter_data['PowerDelivered_total'] * 1000)
                self._dbusservice['/Ac/L1/Energy/Reverse'] = float(meter_data['PowerReturned_total'] * 1000)

            elif phases == '3':
                # Calculate power and current for each phase
                Power1, Current1 = self._calculate_power_and_current(meter_data, 'l1')
                Power2, Current2 = self._calculate_power_and_current(meter_data, 'l2')
                Power3, Current3 = self._calculate_power_and_current(meter_data, 'l3')

                # Send data to DBus for three-phase system
                self._dbusservice['/Ac/Power'] = float(meter_data['PowerDeliveredNetto'])
                self._dbusservice['/Ac/L1/Voltage'] = float(meter_data['Voltage_l1'])
                self._dbusservice['/Ac/L2/Voltage'] = float(meter_data['Voltage_l2'])
                self._dbusservice['/Ac/L3/Voltage'] = float(meter_data['Voltage_l3'])
                self._dbusservice['/Ac/L1/Current'] = Current1
                self._dbusservice['/Ac/L2/Current'] = Current2
                self._dbusservice['/Ac/L3/Current'] = Current3
                self._dbusservice['/Ac/L1/Power'] = Power1
                self._dbusservice['/Ac/L2/Power'] = Power2
                self._dbusservice['/Ac/L3/Power'] = Power3
                self._dbusservice['/Ac/Energy/Forward'] = float(meter_data['PowerDelivered_total'] * 1000)
                self._dbusservice['/Ac/Energy/Reverse'] = float(meter_data['PowerReturned_total'] * 1000)

                logging.info("House Consumption (positive if consuming): %s" % (meter_data['PowerDeliveredNetto']))

            # increment UpdateIndex - to show that new data is available
            index = self._dbusservice['/UpdateIndex'] + 1  # increment index
            if index > 255:   # maximum value of the index
                index = 0       # overflow from 255 to 0
            self._dbusservice['/UpdateIndex'] = index
            self._lastUpdate = time.time()

        except Exception as e:
            logging.critical('Error at %s', '_update', exc_info=e)

        return True
    
    def _handlechangedvalue(self, path, value):
        logging.info("Someone else updated %s to %s", path, value)
        return True  # accept the change

def main():
    logging.basicConfig(level=logging.DEBUG)  # use .INFO for less logging
    logger = logging.getLogger(__name__)
    handler = logging.handlers.SysLogHandler(address='/dev/log')
    logger.addHandler(handler)

    try:
        logger.info("Start")

        from dbus.mainloop.glib import DBusGMainLoop
        DBusGMainLoop(set_as_default=True)

        paths_dbus = {
            '/Ac/Power': {'initial': 0, 'textformat': lambda p, v: str(round(v, 2)) + 'W'},
            '/Ac/Voltage': {'initial': 0, 'textformat': lambda p, v: str(round(v, 2)) + 'V'},
            '/Ac/Current': {'initial': 0, 'textformat': lambda p, v: str(round(v, 2)) + 'A'},
            '/Ac/Energy/Forward': {'initial': 0, 'textformat': lambda p, v: str(round(v, 2)) + 'kWh'},
            '/Ac/Energy/Reverse': {'initial': 0, 'textformat': lambda p, v: str(round(v, 2)) + 'kWh'},
            '/Ac/L1/Voltage': {'initial': 0, 'textformat': lambda p, v: str(round(v, 2)) + 'V'},
            '/Ac/L2/Voltage': {'initial': 0, 'textformat': lambda p, v: str(round(v, 2)) + 'V'},
            '/Ac/L3/Voltage': {'initial': 0, 'textformat': lambda p, v: str(round(v, 2)) + 'V'},
            '/Ac/L1/Current': {'initial': 0, 'textformat': lambda p, v: str(round(v, 2)) + 'A'},
            '/Ac/L2/Current': {'initial': 0, 'textformat': lambda p, v: str(round(v, 2)) + 'A'},
            '/Ac/L3/Current': {'initial': 0, 'textformat': lambda p, v: str(round(v, 2)) + 'A'},
            '/Ac/L1/Power': {'initial': 0, 'textformat': lambda p, v: str(round(v, 2)) + 'W'},
            '/Ac/L2/Power': {'initial': 0, 'textformat': lambda p, v: str(round(v, 2)) + 'W'},
            '/Ac/L3/Power': {'initial': 0, 'textformat': lambda p, v: str(round(v, 2)) + 'W'},
        }
        
        DbusHomeWizzardEnergyP1Service(paths_dbus)
        
        logging.info("Connected to dbus, and switching over to gobject.MainLoop() (= event based)")
        mainloop = gobject.MainLoop()
        mainloop.run()
    
    except (KeyboardInterrupt, SystemExit):
        logging.info("Received interrupt or exit...")

if __name__ == "__main__":
    main()
