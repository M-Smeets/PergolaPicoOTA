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
s1 = Stepper(21,20,19, steps_per_rev=768000, speed_sps=4000)
disable = Pin(22, Pin.OUT)
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

# HTML file
if 'rain' in CLIENT_ID:
    
    html = """<!DOCTYPE html>
    <html>
        <head> <title>Pergola controller with rain sensor</title> </head>
        <body> <h1>Pergola shading control with rain sensor</h1>
            <h3>%s</h3>
            <h4>%s</h4>
            <pre>%s</pre>
        </body>
    </html>
    """
    
elif not 'rain' in CLIENT_ID:
    
    html = """<!DOCTYPE html>
    <html>
        <head> <title>Pergola controller</title> </head>
        <body> <h1>Pergola shading control</h1>
            <h3>%s</h3>
            <h4>%s</h4>
            <pre>%s</pre>
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
    
    
    try:
        #gc.collect()
        
        print("Client connected")
        request_line = await reader.readline()
        print("Request:", request_line)
        
        # We are not interested in HTTP request headers, skip them
        while await reader.readline() != b"\r\n":
            pass

        version = f"MicroPython Version: {sys.version}"

        if '/log' in request_line.split()[1]:
            with open(LOGFILENAME) as file:
                data = file.read()
            heading = "Debug"
            print('log demanded')
        elif '/log1' in request_line.split()[1]:
            with open(LOGFILENAME1) as file:
                data = file.read()
            heading = "Debug1"
            print('log1 demanded')
        elif '/log2' in request_line.split()[1]:
            with open(LOGFILENAME2) as file:
                data = file.read()
            heading = "Debug2"
            print('log2 demanded')
        elif '/log3' in request_line.split()[1]:
            with open(LOGFILENAME3) as file:
                data = file.read()
            heading = "Debug3"
            print('log3 demanded')
        elif '/err' in request_line.split()[1]:
            with open(ERRORLOGFILENAME) as file:
                data = file.read()
            heading = "ERRORS"
        else:
            with open(DATAFILENAME) as file:
                data = file.read()
            heading = "Append '/log' or '/err' to URL to see log file or error log"

        data += gc_text

        response = html % (heading, version, data)
        writer.write('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
        writer.write(response)

        await writer.drain()
        await writer.wait_closed()
        print("Client disconnected")
        await asyncio.sleep_ms(0)
        
    except Exception as e:
        with open(ERRORLOGFILENAME, 'a') as file:
            
            file.write(f"serve_client error @ {timestamp}: {str(e)}\n")

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
            s1.speed(4000) #use low speed for the calibration
             
            while endswitch1() and not alarm(): #wait till the switch is triggered
                disable(0)
                s1.free_run(-1) 
                await asyncio.sleep(1)
                pass
            
        elif endswitch1() and not endswitch2() and not alarm(): 
            await client.publish(PUBLISH_TOPIC1, f"Crash detected, recovery started", qos=1)
            dprint("Crash detected, recovery started")
            LED(1)
            s1.speed(4000) #use low speed for the calibration
             
            while endswitch1() and not alarm(): #wait till the switch is triggered
                disable(0)
                s1.free_run(1) 
                await asyncio.sleep(1)
                pass
            await client.publish(PUBLISH_TOPIC1, f"Recovery successful, homing started", qos=1)
            print("Recovery successful, start homing")
            
        #Homing            
        if not endswitch1() and not alarm():
            LED(1)
            s1.speed(4000) #use low speed for the calibration
            s1.free_run(-1) #move backwards
            disable(0)
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
                    disable(1)
                    dprint("Homing failed!")
                    await client.publish(PUBLISH_TOPIC1, f"Homing failed!", qos=1)
                    await asyncio.sleep(5)
                    machine.soft_reset()
                pass
        
            await asyncio.sleep(0.1)        
            s1.stop() #stop as soon as the switch is triggered
            s1.overwrite_pos(0) #set position as 0 point
            s1.target(0) #set the target to the same value to avoid unwanted movement
            s1.speed(4000) #return to default speed
            s1.track_target() #start stepper again
            disable(1)
            await client.publish(PUBLISH_TOPIC1, f"Homing successful", qos=1)
            dprint("Homing successful")
            
        if alarm():
            await client.publish(PUBLISH_TOPIC1, f"DRIVE ALARM", qos=1)
            s1.stop()
            disable(1)
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
            disable(0)
            
            await client.publish(PUBLISH_TOPIC1, f"Moving from: " + str(s1.get_pos()) + " to "+ str(pos), qos=1)
            await asyncio.sleep(0)
            time.sleep(1)
            
            while s1.get_pos() != pos and not endswitch1():
                
                s1.target(pos)
                pass
            
            updatepos = True
            
        elif s1.get_pos() == pos and not endswitch1() and updatepos:
            disable(1)
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
        disable(1)
        dprint("DRIVE ALARM")
        await homing()

async def OTA():
    
    global cmdOTA
    # Check for OTA updates
    repo_name = "PergolaPicoOTA"
    branch = "refs/heads/main"
    firmware_url = f"https://github.com/MartiMan79/{repo_name}/{branch}/"
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

