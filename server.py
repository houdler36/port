# -*- coding: utf-8 -*-
from flask import Flask, jsonify, request, render_template
import subprocess
import platform
import os
import threading
import time
import schedule
import json
from werkzeug.serving import run_simple

app = Flask(__name__)

# État global
usb_status = "enabled"
schedule_running = False

def is_admin():
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

def get_usb_devices():
    try:
        ps_script = """
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        $result = @()
        $usb_devices = Get-WmiObject Win32_PnPEntity | Where-Object { 
            $_.PNPClass -eq 'USB' -or $_.Name -match 'USB'
        }
        
        foreach ($device in $usb_devices) {
            $disk = if($device.Name -match 'Disk|Storage') {'Disque'} else {'Périphérique'}
            $driveLetter = ''
            
            if ($disk -eq 'Disque') {
                $volumes = Get-WmiObject Win32_DiskDrive | Where-Object { $_.PNPDeviceID -eq $device.DeviceID } | 
                           Get-Disk | Get-Partition | Get-Volume
                $driveLetter = $volumes.DriveLetter -join ','
            }
            
            $result += [PSCustomObject]@{
                name = $device.Name
                manufacturer = $device.Manufacturer
                type = $disk
                drive = if($driveLetter){$driveLetter}else{'-'}
                status = if($device.Status -eq 'OK'){'Actif'}else{'Inactif'}
            }
        }
        $result | ConvertTo-Json -Depth 5
        """
        result = subprocess.run(["powershell", "-Command", ps_script], 
                              capture_output=True, text=True, check=True,
                              encoding='utf-8')
        return json.loads(result.stdout)
    except Exception as e:
        print(f"Erreur détection USB: {str(e)}")
        return []

def toggle_usb():
    global usb_status
    if usb_status == "enabled":
        disable_usb_ports()
        usb_status = "disabled"
    else:
        enable_usb_ports()
        usb_status = "enabled"
    print(f"Statut USB: {usb_status}")

def disable_usb_ports():
    try:
        subprocess.run([
            'reg', 'add', 
            'HKLM\\SYSTEM\\CurrentControlSet\\Services\\USBSTOR', 
            '/v', 'Start', 
            '/t', 'REG_DWORD', 
            '/d', '4', 
            '/f'
        ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.CalledProcessError as e:
        print(f"Erreur désactivation: {e}")

def enable_usb_ports():
    try:
        subprocess.run([
            'reg', 'add', 
            'HKLM\\SYSTEM\\CurrentControlSet\\Services\\USBSTOR', 
            '/v', 'Start', 
            '/t', 'REG_DWORD', 
            '/d', '3', 
            '/f'
        ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.CalledProcessError as e:
        print(f"Erreur activation: {e}")

def schedule_loop():
    global schedule_running
    schedule.every(2).hours.do(toggle_usb)
    while schedule_running:
        schedule.run_pending()
        time.sleep(1)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    devices = get_usb_devices()
    print("=== Données USB ===")
    print(json.dumps(devices, indent=2, ensure_ascii=False))
    return jsonify({
        "status": usb_status,
        "schedule": schedule_running,
        "devices": devices
    })

@app.route('/api/control', methods=['POST'])
def control_usb():
    global usb_status, schedule_running
    
    if not is_admin():
        return jsonify({"error": "Admin privileges required"}), 403
    
    action = request.json.get('action')
    device_index = request.json.get('deviceIndex')  # Récupère l'index du périphérique

    devices = get_usb_devices()  # Récupère la liste des périphériques USB

    if action == "toggle_schedule":
        schedule_running = not schedule_running
        if schedule_running:
            threading.Thread(target=schedule_loop, daemon=True).start()
        return jsonify({
            "success": True,
            "schedule": schedule_running
        })
    elif action == "disable":
        # Désactiver un périphérique spécifique
        if device_index is not None and 0 <= device_index < len(devices):
            device = devices[device_index]
            print(f"Désactivation du périphérique: {device['name']}")
            try:
                ps_script = f"""
                $device = Get-PnpDevice | Where-Object {{ $_.Name -eq '{device['name']}' }}
                if ($device) {{
                    Disable-PnpDevice -InstanceId $device.InstanceId -Confirm:$false
                }}
                """
                subprocess.run(["powershell", "-Command", ps_script], check=True, text=True)
                return jsonify({"success": True, "device": device})
            except subprocess.CalledProcessError as e:
                print(f"Erreur désactivation: {e}")
                return jsonify({"error": "Erreur lors de la désactivation"}), 500
        else:
            return jsonify({"error": "Index de périphérique invalide"}), 400
    elif action == "enable":
        # Activer un périphérique spécifique
        if device_index is not None and 0 <= device_index < len(devices):
            device = devices[device_index]
            print(f"Activation du périphérique: {device['name']}")
            try:
                ps_script = f"""
                $device = Get-PnpDevice | Where-Object {{ $_.Name -eq '{device['name']}' }}
                if ($device) {{
                    Enable-PnpDevice -InstanceId $device.InstanceId -Confirm:$false
                }}
                """
                subprocess.run(["powershell", "-Command", ps_script], check=True, text=True)
                return jsonify({"success": True, "device": device})
            except subprocess.CalledProcessError as e:
                print(f"Erreur activation: {e}")
                return jsonify({"error": "Erreur lors de l'activation"}), 500
        else:
            return jsonify({"error": "Index de périphérique invalide"}), 400
    else:
        return jsonify({"error": "Action invalide"}), 400

if __name__ == '__main__':
    if not is_admin():
        print("ERREUR: Doit être exécuté en tant qu'administrateur")
    else:
        run_simple('0.0.0.0', 5000, app, use_reloader=True)