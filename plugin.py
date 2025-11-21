"""
<plugin key="AristonVelis" name="Ariston Water Heater" author="Based on ariston library" version="2.0.0">
    <description>
        <h2>Ariston Water Heater Plugin</h2><br/>
        Plugin do obsługi podgrzewaczy wody Ariston (Velis, Lydos, Nuos) przez Domoticz<br/>
        Wykorzystuje bibliotekę ariston==0.19.9<br/>
        <ul style="list-style-type:square">
            <li>Odczyt temperatury wody</li>
            <li>Włączanie/wyłączanie podgrzewacza</li>
            <li>Ustawianie temperatury docelowej</li>
            <li>Monitoring trybu pracy</li>
        </ul>
    </description>
    <params>
        <param field="Username" label="Username (email)" width="200px" required="true"/>
        <param field="Password" label="Password" width="200px" required="true" password="true"/>
        <param field="Mode1" label="Gateway ID" width="200px" required="true"/>
        <param field="Mode2" label="Update interval (seconds)" width="75px" required="true" default="180"/>
        <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="True" value="Debug"/>
                <option label="False" value="Normal" default="true"/>
            </options>
        </param>
    </params>
</plugin>
"""

import Domoticz
import sys
import os
import asyncio
import threading

plugin_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(plugin_path)

try:
    from ariston import Ariston, DeviceAttribute
    from ariston.const import ARISTON_API_URL, ARISTON_USER_AGENT
except ImportError as e:
    Domoticz.Error(f"Cannot import ariston library: {e}")
    Domoticz.Error("Install with: sudo pip3 install ariston==0.19.9")
    Ariston = None

class BasePlugin:
    enabled = False
    
    def __init__(self):
        self.ariston = None
        self.device = None
        self.runInterval = 180
        self.heartbeat_counter = 0
        self.update_thread = None
        self.stop_thread = False
        self.loop = None
        
        # Unit IDs
        self.UNIT_TEMP_CURRENT = 1
        self.UNIT_POWER = 2
        self.UNIT_TEMP_TARGET = 3
        self.UNIT_STATUS = 4
        
        return

    def onStart(self):
        Domoticz.Log("Ariston Water Heater plugin started")
        
        if Parameters["Mode6"] == "Debug":
            Domoticz.Debugging(1)
            Domoticz.Debug("Debug mode enabled")
            
        if Ariston is None:
            Domoticz.Error("Ariston library not found!")
            Domoticz.Error("Install: sudo pip3 install ariston==0.19.9")
            return
        
        username = Parameters["Username"]
        password = Parameters["Password"]
        gateway_id = Parameters["Mode1"]
        
        if not username or not password or not gateway_id:
            Domoticz.Error("Username, Password and Gateway ID required!")
            return
        
        try:
            self.runInterval = int(Parameters["Mode2"])
            if self.runInterval < 60:
                self.runInterval = 60
        except:
            self.runInterval = 180
            
        Domoticz.Heartbeat(10)
        
        # Create devices
        if self.UNIT_TEMP_CURRENT not in Devices:
            Domoticz.Device(Name="Current Temperature", Unit=self.UNIT_TEMP_CURRENT, 
                          TypeName="Temperature", Used=1).Create()
            
        if self.UNIT_POWER not in Devices:
            Domoticz.Device(Name="Power", Unit=self.UNIT_POWER, 
                          TypeName="Switch", Switchtype=0, Used=1).Create()
            
        if self.UNIT_TEMP_TARGET not in Devices:
            Domoticz.Device(Name="Target Temperature", Unit=self.UNIT_TEMP_TARGET, 
                          Type=242, Subtype=1, Used=1).Create()
            
        if self.UNIT_STATUS not in Devices:
            Domoticz.Device(Name="Status", Unit=self.UNIT_STATUS, 
                          TypeName="Text", Used=1).Create()
        
        # Start update thread
        self.stop_thread = False
        self.update_thread = threading.Thread(
            target=self.update_loop, 
            args=(username, password, gateway_id)
        )
        self.update_thread.daemon = True
        self.update_thread.start()
        
        Domoticz.Log(f"Plugin configured for gateway {gateway_id}, interval: {self.runInterval}s")

    def onStop(self):
        Domoticz.Log("Ariston plugin stopped")
        self.stop_thread = True
        if self.update_thread:
            self.update_thread.join(timeout=5)

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug(f"onCommand: Unit={Unit}, Command={Command}, Level={Level}")
        
        if not self.device:
            Domoticz.Error("Device not initialized")
            return
            
        try:
            # Run async command in thread
            if Unit == self.UNIT_POWER:
                success = self.run_async_command(self.async_set_power, Command == "On")
                if success:
                    Devices[Unit].Update(nValue=1 if Command == "On" else 0, 
                                       sValue=Command)
                        
            elif Unit == self.UNIT_TEMP_TARGET:
                try:
                    temp = float(Level)
                    min_temp = self.device.water_heater_minimum_temperature or 40
                    max_temp = self.device.water_heater_maximum_temperature or 80
                    
                    if min_temp <= temp <= max_temp:
                        success = self.run_async_command(
                            self.device.async_set_water_heater_temperature, temp
                        )
                        if success:
                            Devices[Unit].Update(nValue=0, sValue=str(temp))
                    else:
                        Domoticz.Error(f"Temperature {temp} out of range {min_temp}-{max_temp}°C")
                except ValueError:
                    Domoticz.Error(f"Invalid temperature value: {Level}")
                    
        except Exception as e:
            Domoticz.Error(f"Command execution error: {str(e)}")
            import traceback
            Domoticz.Error(traceback.format_exc())

    def onHeartbeat(self):
        self.heartbeat_counter += 1

    def update_loop(self, username, password, gateway_id):
        """Main update loop running in separate thread"""
        Domoticz.Log("Update loop started")
        
        # Create new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        try:
            # Initialize connection
            if not self.loop.run_until_complete(
                self.async_connect(username, password, gateway_id)
            ):
                Domoticz.Error("Failed to connect to Ariston")
                return
            
            # Main update loop
            while not self.stop_thread:
                try:
                    self.loop.run_until_complete(self.async_update())
                except Exception as e:
                    Domoticz.Error(f"Update error: {str(e)}")
                    import traceback
                    Domoticz.Error(traceback.format_exc())
                
                # Wait with ability to interrupt
                for _ in range(self.runInterval):
                    if self.stop_thread:
                        break
                    import time
                    time.sleep(1)
                    
        finally:
            self.loop.close()
            Domoticz.Log("Update loop stopped")

    async def async_connect(self, username, password, gateway_id):
        """Connect to Ariston API"""
        try:
            Domoticz.Log("Connecting to Ariston API...")
            
            self.ariston = Ariston()
            
            response = await self.ariston.async_connect(
                username,
                password,
                ARISTON_API_URL,
                ARISTON_USER_AGENT
            )
            
            if not response:
                Domoticz.Error("Connection failed")
                return False
            
            Domoticz.Log("Connected, discovering device...")
            
            # Discover device
            self.device = await self.ariston.async_hello(
                gateway_id,
                True  # metric system
            )
            
            if self.device is None:
                Domoticz.Error(f"Device {gateway_id} not found")
                return False
            
            Domoticz.Log(f"Device found: {self.device.name}")
            
            # Get features
            await self.device.async_get_features()
            
            Domoticz.Log(f"Device type: {self.device.system_type}")
            Domoticz.Log(f"Device model: {self.device.whe_type}")
            
            return True
            
        except Exception as e:
            Domoticz.Error(f"Connection error: {str(e)}")
            import traceback
            Domoticz.Error(traceback.format_exc())
            return False

    async def async_update(self):
        """Update device data"""
        if not self.device:
            return
        
        try:
            Domoticz.Debug("Updating device state...")
            
            # Update state
            await self.device.async_update_state()
            
            # Update current temperature
            current_temp = self.device.water_heater_current_temperature
            if current_temp is not None:
                Devices[self.UNIT_TEMP_CURRENT].Update(nValue=0, sValue=str(current_temp))
                Domoticz.Debug(f"Current temperature: {current_temp}°C")
            
            # Update target temperature
            target_temp = self.device.water_heater_target_temperature
            if target_temp is not None:
                Devices[self.UNIT_TEMP_TARGET].Update(nValue=0, sValue=str(target_temp))
                Domoticz.Debug(f"Target temperature: {target_temp}°C")
            
            # Update power status
            power_value = self.device.water_heater_power_value
            if power_value is not None:
                is_on = bool(power_value)
                Devices[self.UNIT_POWER].Update(
                    nValue=1 if is_on else 0,
                    sValue="On" if is_on else "Off"
                )
                Domoticz.Debug(f"Power: {'On' if is_on else 'Off'}")
            
            # Update status
            mode = self.device.water_heater_current_mode_text
            if mode:
                Devices[self.UNIT_STATUS].Update(nValue=0, sValue=mode)
                Domoticz.Debug(f"Mode: {mode}")
            
            Domoticz.Debug("Update completed successfully")
            
        except Exception as e:
            Domoticz.Error(f"Update error: {str(e)}")
            import traceback
            Domoticz.Error(traceback.format_exc())

    async def async_set_power(self, on):
        """Set power on/off"""
        if not self.device:
            return False
        
        try:
            await self.device.async_set_power(on)
            Domoticz.Log(f"Power set to {'ON' if on else 'OFF'}")
            return True
        except Exception as e:
            Domoticz.Error(f"Set power error: {str(e)}")
            return False

    def run_async_command(self, coro, *args):
        """Run async command from sync context"""
        if not self.loop:
            Domoticz.Error("Event loop not initialized")
            return False
        
        try:
            future = asyncio.run_coroutine_threadsafe(coro(*args), self.loop)
            return future.result(timeout=10)
        except Exception as e:
            Domoticz.Error(f"Async command error: {str(e)}")
            return False


global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()
