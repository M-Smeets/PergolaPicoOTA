import gc
from log import logger
import machine
from machine import Pin, RTC
from mqtt_as import MQTTClient, RP2
from mqtt_local import config
import network
from ntptime import settime
import os
from ota import OTAUpdater
from stepper import Stepper
import sys
import uasyncio as asyncio
import time

if RP2:
    from sys import implementation
    

# define motor controller pins
s1 = Stepper(21,20,19, steps_per_rev=12000, speed_sps=80)
#disable = Pin(22, Pin.OUT)
endswitch1 = Pin(27, Pin.IN, Pin.PULL_UP)
endswitch2 = Pin(28, Pin.IN, Pin.PULL_UP)
alarm = Pin(18, Pin.IN, Pin.PULL_UP)
LED = machine.Pin("LED",machine.Pin.OUT)
rain = Pin(14, Pin.IN, Pin.PULL_UP)
#pin = Pin(18, Pin.OUT)

# Default  MQTT_BROKER to connect to
#MQTT Details
GROUP_ID = config["group_id"]
CLIENT_ID = config["client_id"]

SUBSCRIBE_TOPIC1 = str(GROUP_ID)+"/set_angle"
SUBSCRIBE_TOPIC2 = str(CLIENT_ID)+"/status"
SUBSCRIBE_TOPIC3 = str(GROUP_ID)+"/general"
SUBSCRIBE_TOPIC4 = str(GROUP_ID)+"/rain"
PUBLISH_TOPIC1 = str(CLIENT_ID)+"/status"
PUBLISH_TOPIC2 = str(CLIENT_ID)+"/actPos"
PUBLISH_TOPIC3 = str(CLIENT_ID)+"/info"
PUBLISH_TOPIC4 = str(GROUP_ID)+"/general"
PUBLISH_TOPIC5 = str(GROUP_ID)+"/rain"

# Global values
gc_text = ''
DATAFILENAME = 'data.txt'
LOGFILENAME = 'debug.log'
LOGFILENAME1 = 'debug.log.1'
LOGFILENAME2 = 'debug.log.2'
LOGFILENAME3 = 'debug.log.3'
ERRORLOGFILENAME = 'errorlog.txt'

# Variables
homingneeded = True
pos = 0
setangle = 0
oldTime = 0
currentTime = 0
rssi = -199  # Effectively zero signal in dB.
raining = False
oldval = 0
connected = False
cmdReboot = False
cmdOTA = False

# Raw HTML Headers
HTML_START_RAIN = """<!DOCTYPE html><html><head><title>Pergola controller with rain sensor</title><meta http-equiv="refresh" content="15"></head><body style="font-family:sans-serif; padding:15px;"><h1>Pergola shading control with rain sensor</h1>"""
HTML_START_NORMAL = """<!DOCTYPE html><html><head><title>Pergola controller</title><meta http-equiv="refresh" content="15"></head><body style="font-family:sans-serif; padding:15px;"><h1>Pergola shading control</h1>"""

# Standard Control Buttons
BUTTONS_HTML = """
<div style="display: flex; gap: 10px; margin: 15px 0;">
    <form action="/trigger_ota" method="POST"><button type="submit" style="padding: 10px 20px; background-color: #008CBA; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">OTA Update</button></form>
    <form action="/trigger_reboot" method="POST"><button type="submit" style="padding: 10px 20px; background-color: #f44336; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">Reboot</button></form>
    <form action="/trigger_homing" method="POST"><button type="submit" style="padding: 10px 20px; background-color: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">Force Homing</button></form>
</div>
"""

HTML_END = """<pre>%s</pre></body></html>"""


if 'rain' in CLIENT_ID:
    html_template = """<!DOCTYPE html>
<html>
<head>
    <title>Pergola controller with rain sensor</title>
    <meta http-equiv="refresh" content="15">
</head>
<body>
    <h1>Pergola shading control with rain sensor</h1>
    """ + DASHBOARD_HTML + """
    <h3>{heading}</h3>
    <h4>{version}</h4>
    <pre>{data}</pre>
</body>
</html>
"""
else:
    html_template = """<!DOCTYPE html>
<html>
<head>
    <title>Pergola controller</title>
    <meta http-equiv="refresh" content="15">
</head>
<body>
    <h1>Pergola shading control</h1>
    """ + DASHBOARD_HTML + """
    <h3>{heading}</h3>
    <h4>{version}</h4>
    <pre>{data}</pre>
</body>
</html>
"""


async def log_handling():
    
    global connected
    global timestamp
    
    local_time = time.localtime()
    record("power-up @ (%d, %d, %d, %d, %d, %d, %d, %d)" % local_time)
    
    try:
        #gc.collect()
        
        y = local_time[0]  # curr year
        mo = local_time[1] # current month
        d = local_time[2]  # current day
        h = local_time[3]  # curr hour
        m = local_time[4]  # curr minute
        s = local_time[5]  # curr second
        
        timestamp = f"{h:02}:{m:02}:{s:02}"
        
        # Test WiFi connection twice per minute
        if s in (15, 45):
            if not connected:
                record(f"{timestamp} WiFi not connected")
                
            elif connected:
                get_ntp()
                dprint('ntp done')
                await asyncio.sleep_ms(0)
        
        # Print time on 30 min intervals
        if s in (1,) and not m % 30:
            try:
                record(f"datapoint @ {timestamp}")
                
                gc_text = f"free: {str(gc.mem_free())}\n"
                gc.collect()
                await asyncio.sleep_ms(0)
                
            except Exception as e:
                with open(ERRORLOGFILENAME, 'a') as file:
                    file.write(f"error printing: {repr(e)}\n")

        # Once daily (during the wee hours)
        if h == 9 and m == 33 and s == 59:
            
            # Read lines from previous day
            with open(DATAFILENAME) as f:
                lines = f.readlines()

            # first line is yesterday's date
            yesterdate = lines[0].split()[-1].strip()

            # cull all lines containing '@'
            lines = [line
                     for line in lines
                     if '@' not in line]
            
            # Log lines from previous day
            with open(LOGFILENAME, 'a') as f:
                for line in lines:
                    f.write(line)
            
            # Start a new data file for today
            with open(DATAFILENAME, 'w') as file:
                file.write('Date: %d/%d/%d\n' % (mo, d, y))
            print('file refresh done')
            await asyncio.sleep_ms(0)
        
        


    except Exception as e:
        with open(ERRORLOGFILENAME, 'a') as file:
            file.write(f"logging loop error: {str(e)}\n")



async def serve_client(reader, writer):
    global cmdOTA, cmdReboot, homingneeded, target_pos
    try:
        print("Client connected")
        request_line = await reader.readline()
        if not request_line:
            return

        # Clear remaining HTTP request headers
        while True:
            line = await reader.readline()
            if line == b"\r\n" or line == b"":
                break

        # Parse request target string
        request_str = request_line.decode('utf-8')
        request_path = request_str.split()[1] if len(request_str.split()) > 1 else '/'

        heading = "Append '/log' or '/err' to URL to see log file or error log"
        data = ""

        # Router conditions
        if '/trigger_ota' in request_path:
            cmdOTA = True
            heading = "System Update Action Launched!"
            data = "The module is seeking firmware updates online and will restart shortly...\n"
        elif '/trigger_reboot' in request_path:
            cmdReboot = True
            heading = "System Reboot Requested!"
            data = "The Pico hardware is performing a hard reset sequence...\n"
        elif '/trigger_homing' in request_path:
            homingneeded = True
            heading = "Homing Sequence Force Triggered!"
            data = "The stepper is executing calibration towards the limit switch array...\n"
        elif '/log' in request_path:
            with open(LOGFILENAME) as file: data = file.read()
            heading = "Debug Log"
        elif '/log1' in request_path:
            with open(LOGFILENAME1) as file: data = file.read()
            heading = "Debug1 Log"
        elif '/log2' in request_path:
            with open(LOGFILENAME2) as file: data = file.read()
            heading = "Debug2 Log"
        elif '/log3' in request_path:
            with open(LOGFILENAME3) as file: data = file.read()
            heading = "Debug3 Log"
        elif '/err' in request_path:
            with open(ERRORLOGFILENAME) as file: data = file.read()
            heading = "System Errors Log"
        else:
            with open(DATAFILENAME) as file: data = file.read()

        data += gc_text
        version = f"MicroPython Version: {sys.version}"
        
        # Safely extract position variables
        try:
            act_pos = s1.get_pos()
        except Exception:
            act_pos = 0
            
        louver_deg = round((act_pos / 4500) * 135, 1) if act_pos > 0 else 0.0

        # Construct dashboard segment cleanly using direct concatenation
        status_dashboard = '<div style="margin: 15px 0; padding: 10px; background: #eee; border-radius: 4px; font-weight: bold;">'
        status_dashboard += f"Target Position: {target_pos} steps | "
        status_dashboard += f"Actual Position: {act_pos} steps | "
        status_dashboard += f"Louver Angle: {louver_deg}&deg;"
        status_dashboard += '</div>'

        # Assemble full body transmission 
        if 'rain' in CLIENT_ID:
            response_body = HTML_START_RAIN + BUTTONS_HTML + status_dashboard
        else:
            response_body = HTML_START_NORMAL + BUTTONS_HTML + status_dashboard
            
        response_body += f"<h3>{heading}</h3><h4>{version}</h4>"
        response_body += HTML_END % data

        # Send response header and body cleanly
        writer.write('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
        writer.write(response_body)
        await writer.drain()
        await writer.wait_closed()
        print("Client disconnected cleanly")
        await asyncio.sleep_ms(0)
        
    except Exception as e:
        print("Web server error caught:", str(e))
        try:
            with open(ERRORLOGFILENAME, 'a') as file:
                file.write(f"serve_client crash: {str(e)}\n")
        except:
            pass


def record(line):
    #gc.collect()
    """Combined print and append to data file."""
    print(line)
    line += '\n'
    with open(DATAFILENAME, 'a') as file:
        file.write(line)

def dprint(*args):
    #gc.collect()
    logger.debug(*args)


# Demonstrate scheduler is operational.
async def heartbeat():
    s = True
    while True:
        await asyncio.sleep_ms(500)
        LED(s)
        s = not s

async def wifi_han(state):
    global connected
    s = "rssi: {}dB"
    LED(not state)
    if state:
        connected = True
        dprint('Wifi is up')
        dprint(s.format(rssi))
    else:
        dprint('Wifi is down')
        connected = False
    await asyncio.sleep_ms(0)

async def get_rssi():
    global rssi
    s = network.WLAN()
    ssid = config["ssid"].encode("UTF8")
    #while True:
    try:
        while True:
            
            rssi = [x[3] for x in s.scan() if x[0] == ssid][0]
            
            break
        
    except IndexError:  # ssid not found.
        rssi = -199
        with open(ERRORLOGFILENAME, 'a') as file:
            file.write(f"ssid not found: {str(e)}\n")
            
    await asyncio.sleep(30)

async def get_ntp():
    #gc.collect()
    
    try:
            
        settime()
        rtc = machine.RTC()
        utc_shift = 1

        tm = time.localtime(time.mktime(time.localtime()) + utc_shift*3600)
        tm = tm[0:3] + (0,) + tm[3:6] + (0,)
        rtc.datetime(tm)
        await asyncio.sleep_ms(0)
        
    except OSError as e:
        with open(ERRORLOGFILENAME, 'a') as file:
            file.write(f"OSError while trying to set time: {str(e)}\n")        
        
    print("machine time is:",(time.localtime()))

# If you connect with clean_session True, must re-subscribe (MQTT spec 3.1.2.4)
async def conn_han(client):
    
    await client.subscribe(SUBSCRIBE_TOPIC1, qos=1)
    await client.subscribe(SUBSCRIBE_TOPIC2, qos=1)
    await client.subscribe(SUBSCRIBE_TOPIC3, qos=1)
    await asyncio.sleep_ms(0)

# Subscription callback
def sub_cb(topic, msg, retained):
    
    global pos
    global raining
    global setangle
    global cmdReboot
    global cmdOTA
    
    dprint(f'Topic: "{topic.decode()}" Message: "{msg.decode()}" Retained: {retained}')
    
    if topic.decode() == SUBSCRIBE_TOPIC1:
                
        if not 0 <= int(msg.decode()) <= 288000:
            #dprint(str(msg.decode() + " is no INT"))
            setangle = 0
        else:
            setangle = int(msg.decode())
            
    elif topic.decode() == SUBSCRIBE_TOPIC2:
                        
        if str(msg.decode()) == "Reboot":
            cmdReboot = True
                        
        elif str(msg.decode()) == "Update":
            cmdOTA = True

    
    elif topic.decode() == SUBSCRIBE_TOPIC4:
        if not 'rain' in CLIENT_ID:
            if str(msg.decode()) != "Raining":
                raining = False
                
            elif str(msg.decode()) == "Raining":
                raining = True
                
            

#Inverse input
async def swap_io():
    
    global oldval
    global pos
    #gc.collect()

    if 'rain' in CLIENT_ID:
        if not rain():
            pos = 0
            if oldval == 1 or oldval == 0:
                dprint('Raining')
                await client.publish(PUBLISH_TOPIC5, f"Raining", qos=1)
                oldval = 2
        
        elif rain():
            pos = setangle

            if oldval == 2 or oldval == 0:
                dprint('Ready')
                await client.publish(PUBLISH_TOPIC5, f"Not raining", qos=1)
                oldval = 1
            
    elif not 'rain' in CLIENT_ID:
        if not raining:
            pos = setangle

            if oldval == 1 or oldval == 0:
                dprint('Not raining')
                oldval = 2
            
        elif raining:
            pos = 0
            if oldval == 2 or oldval == 0:
                dprint('Raining')
                oldval = 1
    await asyncio.sleep_ms(0)
    
async def reboot():
    
    await client.publish(PUBLISH_TOPIC1, f"Re-booting", qos=1)
    client.close()
    await asyncio.sleep(5)
    machine.reset()      

async def runOTA():
    
    await client.publish(PUBLISH_TOPIC1, f"Updating", qos=1)
    await asyncio.sleep(5)
    await OTA()

# Homing sequence
async def homing():
    
    global homingneeded
    #gc.collect()

    while True:
        
        await asyncio.sleep(1)
        await client.publish(PUBLISH_TOPIC1, f"Homing", qos=1)
        dprint("Homing")

        #Crash recovery
        if endswitch1() and endswitch2() and not alarm():
            
            await client.publish(PUBLISH_TOPIC1, f"Crash detected, recovery started", qos=1)
            dprint("Crash detected, recovery started")
            LED(1)
            s1.speed(80) #use low speed for the calibration
             
            while endswitch1() and not alarm(): #wait till the switch is triggered
                s1.en_pin(0)
                s1.free_run(-1) 
                await asyncio.sleep(1)
                pass
            
        elif endswitch1() and not endswitch2() and not alarm(): 
            await client.publish(PUBLISH_TOPIC1, f"Crash detected, recovery started", qos=1)
            dprint("Crash detected, recovery started")
            LED(1)
            s1.speed(80) #use low speed for the calibration
             
            while endswitch1() and not alarm(): #wait till the switch is triggered
                s1.en_pin(0)
                s1.free_run(1) 
                await asyncio.sleep(1)
                pass
            await client.publish(PUBLISH_TOPIC1, f"Recovery successful, homing started", qos=1)
            print("Recovery successful, start homing")
            
        #Homing            
        if not endswitch1() and not alarm():
            LED(1)
            s1.speed(80) #use low speed for the calibration
            s1.free_run(-1) #move backwards
            s1.en_pin(0)
            while endswitch1.value() == 0 and not alarm(): #wait till the switch is triggered
                pass
        
            s1.stop() #stop as soon as the switch is triggered
            s1.overwrite_pos(0) #set position as 0 point
            s1.target(0) #set the target to the same value to avoid unwanted movement
            await client.publish(PUBLISH_TOPIC2, str(s1.get_pos()), qos=1)
            homingneeded = False
            s1.free_run(1) #move forwards

            now = time.time()
            delay = 3
            while endswitch1.value() == 1 and not alarm(): #wait till the switch is triggered
                if time.time() > now + delay:
                    s1.stop()
                    s1.en_pin(1)
                    dprint("Homing failed!")
                    await client.publish(PUBLISH_TOPIC1, f"Homing failed!", qos=1)
                    await asyncio.sleep(5)
                    machine.soft_reset()
                pass
        
            await asyncio.sleep(0.1)        
            s1.stop() #stop as soon as the switch is triggered
            s1.overwrite_pos(0) #set position as 0 point
            s1.target(0) #set the target to the same value to avoid unwanted movement
            s1.speed(80) #return to default speed
            s1.track_target() #start stepper again
            s1.en_pin(1)
            await client.publish(PUBLISH_TOPIC1, f"Homing successful", qos=1)
            dprint("Homing successful")
            
        if alarm():
            await client.publish(PUBLISH_TOPIC1, f"DRIVE ALARM", qos=1)
            s1.stop()
            s1.en_pin(1)
            dprint("DRIVE ALARM")
            await homing()
        LED(0)
        await asyncio.sleep_ms(0)
        break

# Standard operating sequence
async def motion():
    
    global cmdOTA
    global cmdReboot
    oldVal = False
    updatepos = False
    s = "rssi: {}dB"

    while True and not alarm():
        
        gc.collect()
        m = gc.mem_free()
        i = 0           
        
        if s1.get_pos() != pos and not endswitch1():
            s1.en_pin(0)
            
            await client.publish(PUBLISH_TOPIC1, f"Moving from: " + str(s1.get_pos()) + " to "+ str(pos), qos=1)
            await asyncio.sleep(0)
            time.sleep(1)
            
            while s1.get_pos() != pos and not endswitch1():
                
                s1.target(pos)
                pass
            
            updatepos = True
            
        elif s1.get_pos() == pos and not endswitch1() and updatepos:
            s1.en_pin(1)
            await client.publish(PUBLISH_TOPIC1, f"Ready", qos=1)
            await client.publish(PUBLISH_TOPIC2, str(s1.get_pos()), qos=1)
            await client.publish(PUBLISH_TOPIC3, s.format(rssi, m), qos=1)
            dprint("Ready")
            dprint("Moved to: "+ str(pos))
            dprint(s.format(rssi))
            await asyncio.sleep(0.5)
            updatepos = False
         
        elif cmdReboot:
            await reboot()
             
        elif cmdOTA:
            await runOTA()
        elif cmdReboot:
            await reboot()
        elif homingneeded:  # <--- ADD THIS INTERCEPT BLOCK
            dprint("Breaking motion loop to execute web-triggered homing cycle.")
            break

    
        
        # Crash detection
        elif endswitch1():
            await client.publish(PUBLISH_TOPIC1, f"Positioning error!", qos=1)
            dprint("Positioning error!")
            await homing()
            break
        
        await swap_io()
        await asyncio.sleep_ms(0)

    while True and alarm():
        
        if not oldVal:
                    
            await client.publish(PUBLISH_TOPIC1, f"DRIVE ALARM", qos=1)
            oldVal = True
            
        s1.stop()
        s1.en_pin(1)
        dprint("DRIVE ALARM")
        await homing()

async def OTA():
    
    global cmdOTA
    # Check for OTA updates
    repo_name = "PergolaPicoOTA"
    branch = "refs/heads/main"
    firmware_url = f"https://github.com/M-Smeets/{repo_name}/{branch}/"
    ota_updater = OTAUpdater(firmware_url,
                             "main.py",
                             "ota.py",
                             "log.py",
                             "lib/ntptime.py",
                             "lib/logging/handlers.py",
                             "lib/logging/__init__.py",
                             "lib/stepper/__init__.py",
                             )
    ota_updater.download_and_install_update_if_available()
    cmdOTA = False
    await client.publish(PUBLISH_TOPIC1, f"No update available", qos=1)
    await asyncio.sleep_ms(0)

async def main():

    try:
        await client.connect()
        await get_ntp()

    except OSError:
        
        with open(ERRORLOGFILENAME, 'a') as file:
            file.write(f"Connection failed: {str(e)}\n")
        return
    
    asyncio.create_task(get_rssi())
    asyncio.create_task(log_handling())
    asyncio.create_task(asyncio.start_server(serve_client, "0.0.0.0", 80))
    
    await client.publish(PUBLISH_TOPIC3, f'Connected', qos=1)
    await client.publish(PUBLISH_TOPIC4, f'Ready', qos=1)
    dprint("Startup ready")
    
    while True and homingneeded == True:
        
        await homing()
        break
    
    while True:

        await motion()
        

# Define configuration
config['subs_cb'] = sub_cb
config['wifi_coro'] = wifi_han
config['connect_coro'] = conn_han
config['clean'] = True

if 'rain' in CLIENT_ID:
    config['will'] = (PUBLISH_TOPIC4, f'pico_w_pergola/rain_sensor lost connection', False, 0)
elif not 'rain' in CLIENT_ID:
    config['will'] = (PUBLISH_TOPIC4, f'pico_w_pergola/no_sensor lost connection', False, 0)

config['keepalive'] = 120

# Set up client
MQTTClient.DEBUG = False  # Optional
client = MQTTClient(config)
    
asyncio.create_task(heartbeat())

try:
    asyncio.run(main())
    
finally:
    client.close()  # Prevent LmacRxBlk:1 errors
    asyncio.new_event_loop()

