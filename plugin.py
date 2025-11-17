"""
<plugin key="AristonDHW" name="Ariston Water Heater" author="Based on aristonremotethermo" version="1.0.0">
    <description>
        <h2>Ariston Water Heater Plugin</h2><br/>
        Plugin do obsługi podgrzewaczy wody Ariston przez Domoticz<br/>
        <ul style="list-style-type:square">
            <li>Odczyt temperatury wody</li>
            <li>Włączanie/wyłączanie podgrzewacza</li>
            <li>Monitoring trybu pracy DHW</li>
        </ul>
    </description>
    <params>
        <param field="Username" label="Username (email)" width="200px" required="true"/>
        <param field="Password" label="Password" width="200px" required="true" password="true"/>
        <param field="Mode1" label="Gateway ID (hex format, np. 14335CF112FC)" width="200px" required="false" default=""/>
        <param field="Mode2" label="Update interval (seconds)" width="75px" required="true" default="60"/>
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
import logging

# Dodaj ścieżkę do biblioteki ariston
plugin_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(plugin_path)

# Skonfiguruj logging dla biblioteki ariston aby przekierowywać do Domoticza
class DomoticzLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            if record.levelno >= logging.ERROR:
                Domoticz.Error(f"[Ariston] {msg}")
            elif record.levelno >= logging.WARNING:
                Domoticz.Log(f"[Ariston WARNING] {msg}")
            elif record.levelno >= logging.INFO:
                Domoticz.Log(f"[Ariston] {msg}")
            else:
                Domoticz.Debug(f"[Ariston] {msg}")
        except:
            pass

try:
    from aristonremotethermo import ariston
    # Dodaj handler do loggera biblioteki ariston
    ariston_logger = logging.getLogger('aristonremotethermo.ariston')
    ariston_logger.addHandler(DomoticzLogHandler())
    ariston_logger.setLevel(logging.DEBUG)
except ImportError:
    ariston = None

class BasePlugin:
    enabled = False
    
    def __init__(self):
        self.ariston_handler = None
        self.runInterval = 60
        self.heartbeat_counter = 0
        
        # Unit IDs dla urządzeń
        self.UNIT_DHW_TEMP = 1
        self.UNIT_DHW_SWITCH = 2
        self.UNIT_DHW_MODE = 3
        self.UNIT_DHW_SET_TEMP = 4
        
        return

    def onStart(self):
        Domoticz.Log("Ariston Water Heater plugin started")
        
        if Parameters["Mode6"] == "Debug":
            Domoticz.Debugging(1)
            Domoticz.Debug("Tryb debugowania włączony")
            
        if ariston is None:
            Domoticz.Error("Nie można zaimportować biblioteki aristonremotethermo!")
            Domoticz.Error("Upewnij się, że folder 'aristonremotethermo' znajduje się w katalogu pluginu")
            return
        
        # Sprawdź czy requests jest zainstalowany
        try:
            import requests
            Domoticz.Debug(f"Moduł requests znaleziony: {requests.__version__}")
        except ImportError:
            Domoticz.Error("Brak modułu 'requests'! Zainstaluj: sudo pip3 install requests")
            return
            
        # Pobierz parametry
        username = Parameters["Username"]
        password = Parameters["Password"]
        gateway_id = Parameters["Mode1"] if Parameters["Mode1"] else ""
        
        if not username or not password:
            Domoticz.Error("Username i Password są wymagane!")
            return
        
        Domoticz.Debug(f"Username: {username}")
        Domoticz.Debug(f"Gateway ID: {gateway_id if gateway_id else 'Auto-detect'}")
        
        try:
            self.runInterval = int(Parameters["Mode2"])
            if self.runInterval < 30:
                self.runInterval = 30
                Domoticz.Log(f"Minimalny interwał to 30 sekund, ustawiono: {self.runInterval}")
        except:
            self.runInterval = 60
            
        Domoticz.Heartbeat(10)  # Co 10 sekund sprawdzamy
        
        # Utwórz urządzenia jeśli nie istnieją
        if self.UNIT_DHW_TEMP not in Devices:
            Domoticz.Device(Name="DHW Temperature", Unit=self.UNIT_DHW_TEMP, 
                          TypeName="Temperature", Used=1).Create()
            Domoticz.Log("Utworzono urządzenie: DHW Temperature")
            
        if self.UNIT_DHW_SWITCH not in Devices:
            Domoticz.Device(Name="DHW Power", Unit=self.UNIT_DHW_SWITCH, 
                          TypeName="Switch", Switchtype=0, Used=1).Create()
            Domoticz.Log("Utworzono urządzenie: DHW Power")
            
        if self.UNIT_DHW_MODE not in Devices:
            Domoticz.Device(Name="DHW Mode", Unit=self.UNIT_DHW_MODE, 
                          TypeName="Text", Used=1).Create()
            Domoticz.Log("Utworzono urządzenie: DHW Mode")
            
        if self.UNIT_DHW_SET_TEMP not in Devices:
            Domoticz.Device(Name="DHW Set Temperature", Unit=self.UNIT_DHW_SET_TEMP, 
                          Type=242, Subtype=1, Used=1).Create()
            Domoticz.Log("Utworzono urządzenie: DHW Set Temperature")
        
        # Inicjalizuj handler Ariston
        try:
            sensors_list = [
                'dhw_set_temperature',
                'dhw_storage_temperature',
                'dhw_mode',
                'mode'
            ]
            
            Domoticz.Log(f"Inicjalizacja handlera z interwałem {self.runInterval}s")
            Domoticz.Log(f"Gateway ID: '{gateway_id}'")
            
            # Ustaw poziom logowania dla biblioteki ariston
            log_level = 'DEBUG' if Parameters["Mode6"] == "Debug" else 'INFO'
            
            self.ariston_handler = ariston.AristonHandler(
                username=username,
                password=password,
                sensors=sensors_list,
                logging_level=log_level,
                period_get_request=self.runInterval,
                gw=gateway_id
            )
            
            Domoticz.Log("Handler utworzony, subskrybowanie callbacków...")
            
            # Subskrybuj zmiany
            self.ariston_handler.subscribe_sensors(self.sensor_update_callback)
            self.ariston_handler.subscribe_statuses(self.status_update_callback)
            
            Domoticz.Log("Uruchamianie handlera...")
            
            # Uruchom handler
            self.ariston_handler.start()
            Domoticz.Log("Handler Ariston został uruchomiony - oczekiwanie na połączenie...")
            Domoticz.Log("Pierwsze dane powinny pojawić się w ciągu 60 sekund")
            
        except Exception as e:
            Domoticz.Error(f"Błąd podczas inicjalizacji handlera: {str(e)}")
            import traceback
            Domoticz.Error(f"Traceback: {traceback.format_exc()}")
            self.ariston_handler = None

    def onStop(self):
        Domoticz.Log("Ariston Water Heater plugin stopped")
        if self.ariston_handler:
            try:
                self.ariston_handler.stop()
            except:
                pass

    def onConnect(self, Connection, Status, Description):
        pass

    def onMessage(self, Connection, Data):
        pass

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug(f"onCommand called for Unit {Unit}: Command '{Command}', Level: {Level}")
        
        if not self.ariston_handler:
            Domoticz.Error("Handler Ariston nie jest zainicjalizowany")
            return
            
        try:
            if Unit == self.UNIT_DHW_SWITCH:
                # Włączanie/wyłączanie DHW
                if Command == "On":
                    self.ariston_handler.set_http_data(mode="Summer")
                    Devices[Unit].Update(nValue=1, sValue="On")
                    Domoticz.Log("DHW włączony (tryb Summer)")
                elif Command == "Off":
                    self.ariston_handler.set_http_data(mode="OFF")
                    Devices[Unit].Update(nValue=0, sValue="Off")
                    Domoticz.Log("DHW wyłączony")
                    
            elif Unit == self.UNIT_DHW_SET_TEMP:
                # Ustawianie temperatury
                try:
                    temp_value = float(Level)
                    self.ariston_handler.set_http_data(dhw_set_temperature=temp_value)
                    Devices[Unit].Update(nValue=0, sValue=str(temp_value))
                    Domoticz.Log(f"Ustawiono temperaturę DHW na: {temp_value}°C")
                except ValueError:
                    Domoticz.Error(f"Nieprawidłowa wartość temperatury: {Level}")
                    
        except Exception as e:
            Domoticz.Error(f"Błąd podczas wykonywania komendy: {str(e)}")

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        pass

    def onDisconnect(self, Connection):
        pass

    def onHeartbeat(self):
        self.heartbeat_counter += 1
        
        # Co 10 cykli heartbeat sprawdź status (100 sekund)
        if self.heartbeat_counter >= 10:
            self.heartbeat_counter = 0
            if self.ariston_handler:
                try:
                    available = self.ariston_handler.available
                    dhw_available = self.ariston_handler.dhw_available
                    
                    Domoticz.Debug(f"Status check - Available: {available}, DHW: {dhw_available}")
                    
                    if not available:
                        Domoticz.Error("Połączenie z Ariston niedostępne")
                        Domoticz.Debug(f"Plant ID: {self.ariston_handler.plant_id}")
                        
                        # Sprawdź czy są dane
                        sensor_values = self.ariston_handler.sensor_values
                        Domoticz.Debug(f"Liczba sensorów z danymi: {len([k for k,v in sensor_values.items() if v.get('value') is not None])}")
                    else:
                        Domoticz.Debug("Połączenie aktywne")
                        
                except Exception as e:
                    Domoticz.Error(f"Błąd podczas sprawdzania statusu: {str(e)}")
            else:
                Domoticz.Error("Handler Ariston nie jest zainicjalizowany")

    def sensor_update_callback(self, changed_data, *args, **kwargs):
        """Callback wywoływany gdy zmieniają się wartości sensorów"""
        try:
            Domoticz.Debug(f"Sensor update: {list(changed_data.keys())}")
            
            # Aktualizuj temperaturę wody
            if 'dhw_storage_temperature' in changed_data:
                temp = changed_data['dhw_storage_temperature'].get('value')
                if temp is not None:
                    Devices[self.UNIT_DHW_TEMP].Update(nValue=0, sValue=str(temp))
                    Domoticz.Debug(f"Zaktualizowano temperaturę DHW: {temp}°C")
            
            # Aktualizuj temperaturę nastawioną
            if 'dhw_set_temperature' in changed_data:
                temp = changed_data['dhw_set_temperature'].get('value')
                if temp is not None:
                    Devices[self.UNIT_DHW_SET_TEMP].Update(nValue=0, sValue=str(temp))
                    Domoticz.Debug(f"Zaktualizowano nastawę temperatury DHW: {temp}°C")
            
            # Aktualizuj tryb DHW
            if 'dhw_mode' in changed_data:
                mode = changed_data['dhw_mode'].get('value')
                if mode is not None:
                    Devices[self.UNIT_DHW_MODE].Update(nValue=0, sValue=str(mode))
                    Domoticz.Debug(f"Zaktualizowano tryb DHW: {mode}")
            
            # Aktualizuj przełącznik na podstawie trybu głównego
            if 'mode' in changed_data:
                mode = changed_data['mode'].get('value')
                if mode is not None:
                    if mode == "OFF":
                        Devices[self.UNIT_DHW_SWITCH].Update(nValue=0, sValue="Off")
                    else:
                        Devices[self.UNIT_DHW_SWITCH].Update(nValue=1, sValue="On")
                    Domoticz.Debug(f"Zaktualizowano stan przełącznika: {mode}")
                    
        except Exception as e:
            Domoticz.Error(f"Błąd w callback aktualizacji sensorów: {str(e)}")

    def status_update_callback(self, changed_status, *args, **kwargs):
        """Callback wywoływany gdy zmienia się status połączenia"""
        try:
            Domoticz.Debug(f"Status update: {changed_status}")
            
            if 'available' in changed_status:
                if changed_status['available']:
                    Domoticz.Log("Połączenie z Ariston aktywne")
                else:
                    Domoticz.Error("Połączenie z Ariston nieaktywne")
                    
            if 'dhw_available' in changed_status:
                if changed_status['dhw_available']:
                    Domoticz.Log("DHW dostępny")
                else:
                    Domoticz.Log("DHW niedostępny")
                    
        except Exception as e:
            Domoticz.Error(f"Błąd w callback aktualizacji statusu: {str(e)}")

global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)

def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    global _plugin
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()
