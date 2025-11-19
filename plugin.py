"""
<plugin key="AristonVelis" name="Ariston Velis Water Heater" author="Based on ariston library" version="1.0.0">
    <description>
        <h2>Ariston Velis Water Heater Plugin</h2><br/>
        Plugin do obsługi podgrzewaczy wody Ariston Velis przez Domoticz<br/>
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
        <param field="Mode1" label="Gateway ID (14335CF112FC)" width="200px" required="true"/>
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
import json
import threading
import time

# Dodaj ścieżkę do katalogu pluginu
plugin_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(plugin_path)

try:
    import requests
except ImportError:
    requests = None

class AristonVelisAPI:
    """Prosta klasa do komunikacji z API Ariston Velis"""
    
    def __init__(self, username, password, gateway_id):
        self.username = username
        self.password = password
        self.gateway_id = gateway_id
        self.base_url = "https://www.ariston-net.remotethermo.com"
        self.session = requests.Session()
        self.logged_in = False
        self.data = {}
        
    def login(self):
        """Zaloguj się do API Ariston"""
        try:
            login_data = {
                "email": self.username,
                "password": self.password,
                "rememberMe": False,
                "language": "English_Us"
            }
            
            resp = self.session.post(
                f'{self.base_url}/R2/Account/Login?returnUrl=%2FR2%2FHome',
                json=login_data,
                timeout=15,
                verify=True
            )
            
            if resp.ok:
                self.logged_in = True
                Domoticz.Log("Logged in successfully")
                return True
            else:
                Domoticz.Error(f"Login failed: {resp.status_code}")
                return False
                
        except Exception as e:
            Domoticz.Error(f"Login exception: {str(e)}")
            return False
    
    def get_plant_data(self):
        """Pobierz dane o urządzeniu"""
        if not self.logged_in:
            if not self.login():
                return None
        
        try:
            # Pobierz listę urządzeń Velis
            resp = self.session.get(
                f'{self.base_url}/api/v2/velis/plants',
                timeout=15,
                verify=True
            )
            
            if not resp.ok:
                Domoticz.Error(f"Failed to get plants: {resp.status_code}")
                return None
            
            plants = resp.json()
            
            # Znajdź nasze urządzenie
            for plant in plants:
                if plant.get('gw') == self.gateway_id:
                    self.data = plant
                    Domoticz.Debug(f"Plant data: {json.dumps(plant, indent=2)}")
                    return plant
            
            Domoticz.Error(f"Gateway {self.gateway_id} not found in plants")
            return None
            
        except Exception as e:
            Domoticz.Error(f"Get plant data exception: {str(e)}")
            return None
    
    def get_temperature_data(self):
        """Pobierz dane o temperaturze z menu"""
        try:
            # Parametry Velis z menu
            params = [
                "MedSetpointTemperature",  # Temperatura docelowa
                "ProcReqTemp",  # Aktualna temperatura
            ]
            
            resp = self.session.get(
                f'{self.base_url}/R2/SlpPlantData/GetData/{self.gateway_id}',
                timeout=15,
                verify=True
            )
            
            if resp.ok:
                data = resp.json()
                Domoticz.Debug(f"Temperature data: {json.dumps(data, indent=2)}")
                return data
            else:
                Domoticz.Debug(f"GetData failed, trying alternative: {resp.status_code}")
                
                # Alternatywna metoda przez menu
                resp = self.session.get(
                    f'{self.base_url}/R2/PlantMenu/Refresh?id={self.gateway_id}&paramIds=MedSetpointTemperature',
                    timeout=15
                )
                
                if resp.ok:
                    data = resp.json()
                    Domoticz.Debug(f"Menu data: {json.dumps(data, indent=2)}")
                    return data
                    
            return None
            
        except Exception as e:
            Domoticz.Error(f"Get temperature data exception: {str(e)}")
            return None
    
    def set_power(self, on):
        """Włącz/wyłącz podgrzewacz"""
        try:
            value = 1 if on else 0
            
            resp = self.session.post(
                f'{self.base_url}/api/v2/velis/slp-plant-data/{self.gateway_id}/switch',
                json={"new": value, "old": 1 - value},
                timeout=15
            )
            
            if resp.ok:
                Domoticz.Log(f"Power set to {'ON' if on else 'OFF'}")
                return True
            else:
                Domoticz.Error(f"Set power failed: {resp.status_code}")
                return False
                
        except Exception as e:
            Domoticz.Error(f"Set power exception: {str(e)}")
            return False
    
    def set_temperature(self, temp):
        """Ustaw temperaturę docelową"""
        try:
            resp = self.session.post(
                f'{self.base_url}/api/v2/velis/med-plant-data/{self.gateway_id}/temperature',
                json={"new": temp, "old": self.data.get('reqTemp', 60)},
                timeout=15
            )
            
            if resp.ok:
                Domoticz.Log(f"Temperature set to {temp}°C")
                return True
            else:
                Domoticz.Error(f"Set temperature failed: {resp.status_code}")
                return False
                
        except Exception as e:
            Domoticz.Error(f"Set temperature exception: {str(e)}")
            return False


class BasePlugin:
    enabled = False
    
    def __init__(self):
        self.api = None
        self.runInterval = 180
        self.heartbeat_counter = 0
        self.update_thread = None
        self.stop_thread = False
        
        # Unit IDs
        self.UNIT_TEMP_CURRENT = 1
        self.UNIT_POWER = 2
        self.UNIT_TEMP_TARGET = 3
        self.UNIT_STATUS = 4
        
        return

    def onStart(self):
        Domoticz.Log("Ariston Velis Water Heater plugin started")
        
        if Parameters["Mode6"] == "Debug":
            Domoticz.Debugging(1)
            Domoticz.Debug("Tryb debugowania włączony")
            
        if requests is None:
            Domoticz.Error("Brak modułu 'requests'! Zainstaluj: sudo pip3 install requests")
            return
        
        # Parametry
        username = Parameters["Username"]
        password = Parameters["Password"]
        gateway_id = Parameters["Mode1"]
        
        if not username or not password or not gateway_id:
            Domoticz.Error("Username, Password i Gateway ID są wymagane!")
            return
        
        try:
            self.runInterval = int(Parameters["Mode2"])
            if self.runInterval < 60:
                self.runInterval = 60
        except:
            self.runInterval = 180
            
        Domoticz.Heartbeat(10)
        
        # Utwórz urządzenia
        if self.UNIT_TEMP_CURRENT not in Devices:
            Domoticz.Device(Name="Temperatura aktualna", Unit=self.UNIT_TEMP_CURRENT, 
                          TypeName="Temperature", Used=1).Create()
            
        if self.UNIT_POWER not in Devices:
            Domoticz.Device(Name="Zasilanie", Unit=self.UNIT_POWER, 
                          TypeName="Switch", Switchtype=0, Used=1).Create()
            
        if self.UNIT_TEMP_TARGET not in Devices:
            Domoticz.Device(Name="Temperatura docelowa", Unit=self.UNIT_TEMP_TARGET, 
                          Type=242, Subtype=1, Used=1).Create()
            
        if self.UNIT_STATUS not in Devices:
            Domoticz.Device(Name="Status", Unit=self.UNIT_STATUS, 
                          TypeName="Text", Used=1).Create()
        
        # Inicjalizuj API
        self.api = AristonVelisAPI(username, password, gateway_id)
        
        Domoticz.Log(f"Plugin skonfigurowany dla gateway {gateway_id}, interwał: {self.runInterval}s")
        
        # Uruchom wątek aktualizacji
        self.stop_thread = False
        self.update_thread = threading.Thread(target=self.update_loop)
        self.update_thread.daemon = True
        self.update_thread.start()

    def onStop(self):
        Domoticz.Log("Ariston Velis plugin stopped")
        self.stop_thread = True
        if self.update_thread:
            self.update_thread.join(timeout=5)

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug(f"onCommand: Unit={Unit}, Command={Command}, Level={Level}")
        
        if not self.api:
            return
            
        try:
            if Unit == self.UNIT_POWER:
                if Command == "On":
                    if self.api.set_power(True):
                        Devices[Unit].Update(nValue=1, sValue="On")
                elif Command == "Off":
                    if self.api.set_power(False):
                        Devices[Unit].Update(nValue=0, sValue="Off")
                        
            elif Unit == self.UNIT_TEMP_TARGET:
                try:
                    temp = float(Level)
                    if 40 <= temp <= 80:  # Zakres typowy dla Velis
                        if self.api.set_temperature(temp):
                            Devices[Unit].Update(nValue=0, sValue=str(temp))
                    else:
                        Domoticz.Error(f"Temperatura {temp} poza zakresem 40-80°C")
                except ValueError:
                    Domoticz.Error(f"Nieprawidłowa wartość temperatury: {Level}")
                    
        except Exception as e:
            Domoticz.Error(f"Błąd wykonywania komendy: {str(e)}")

    def onHeartbeat(self):
        self.heartbeat_counter += 1
        # Heartbeat co 10s, ale aktualizacja jest w osobnym wątku

    def update_loop(self):
        """Główna pętla aktualizacji danych"""
        Domoticz.Log("Update loop started")
        
        while not self.stop_thread:
            try:
                self.update_data()
            except Exception as e:
                Domoticz.Error(f"Update loop error: {str(e)}")
            
            # Czekaj z możliwością przerwania
            for _ in range(self.runInterval):
                if self.stop_thread:
                    break
                time.sleep(1)
        
        Domoticz.Log("Update loop stopped")
    
    def update_data(self):
        """Pobierz i zaktualizuj dane z API"""
        if not self.api:
            return
        
        try:
            # Pobierz dane podstawowe
            plant_data = self.api.get_plant_data()
            if not plant_data:
                Devices[self.UNIT_STATUS].Update(nValue=0, sValue="Offline")
                return
            
            # Pobierz dane o temperaturze
            temp_data = self.api.get_temperature_data()
            
            # Zaktualizuj status
            is_online = not plant_data.get('isOffline48H', True)
            link_status = plant_data.get('lnk', 0)
            
            status_text = "Online" if is_online and link_status == 1 else "Offline"
            Devices[self.UNIT_STATUS].Update(nValue=0, sValue=status_text)
            
            # Zaktualizuj dane jeśli dostępne
            if temp_data and isinstance(temp_data, dict):
                # Próbuj różne klucze dla temperatury
                current_temp = None
                target_temp = None
                
                if 'data' in temp_data:
                    for item in temp_data['data']:
                        if 'MedSetpointTemperature' in item.get('id', ''):
                            target_temp = item.get('value')
                        elif 'ProcReqTemp' in item.get('id', ''):
                            current_temp = item.get('value')
                
                if current_temp is not None:
                    Devices[self.UNIT_TEMP_CURRENT].Update(nValue=0, sValue=str(current_temp))
                    Domoticz.Debug(f"Aktualna temperatura: {current_temp}°C")
                
                if target_temp is not None:
                    Devices[self.UNIT_TEMP_TARGET].Update(nValue=0, sValue=str(target_temp))
                    Domoticz.Debug(f"Temperatura docelowa: {target_temp}°C")
            
            Domoticz.Debug("Data updated successfully")
            
        except Exception as e:
            Domoticz.Error(f"Update data error: {str(e)}")
            import traceback
            Domoticz.Error(traceback.format_exc())


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
